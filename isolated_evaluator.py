"""
GhostDev - Out-Of-Band Isolated Evaluation Harness Controller
=============================================================
Enforces total decoupling between Coder-Agent (Worker) and the evaluation harness.
Eliminates second-order reward hacking (fixture tampering, default parameter manipulation,
or test configuration bypass) by provisioning ephemeral execution sandboxes and verifying
AST invariants before running out-of-band test suites.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Set, Tuple


# Configuration & Forbidden Target Patterns for Workspace Isolation
FORBIDDEN_DIFF_PATTERNS = [
    r"^tests?(/|\\|$)",
    r"(^|/|\\)conftest\.py$",
    r"(^|/|\\)pytest\.ini$",
    r"(^|/|\\)setup\.(py|cfg)$",
    r"(^|/|\\)pyproject\.toml$",
    r"(^|/|\\)requirements.*\.txt$",
    r"(^|/|\\)\.pytest_cache(/|\\|$)",
    r"(^|/|\\)\.github(/|\\|$)",
    r"(^|/|\\)\.env.*$",
    r"(^|/|\\)tox\.ini$",
]


class FunctionSignature:
    """Represents a normalized representation of a Python function signature."""

    def __init__(
        self,
        name: str,
        posonlyargs: List[str],
        args: List[str],
        vararg: Optional[str],
        kwonlyargs: List[str],
        kw_defaults: List[Optional[str]],
        kwarg: Optional[str],
        defaults: List[str],
        is_async: bool = False,
    ):
        self.name = name
        self.posonlyargs = posonlyargs
        self.args = args
        self.vararg = vararg
        self.kwonlyargs = kwonlyargs
        self.kw_defaults = kw_defaults
        self.kwarg = kwarg
        self.defaults = defaults
        self.is_async = is_async

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, FunctionSignature):
            return False
        return (
            self.name == other.name
            and self.posonlyargs == other.posonlyargs
            and self.args == other.args
            and self.vararg == other.vararg
            and self.kwonlyargs == other.kwonlyargs
            and self.kw_defaults == other.kw_defaults
            and self.kwarg == other.kwarg
            and self.defaults == other.defaults
            and self.is_async == other.is_async
        )

    def describe_diff(self, other: "FunctionSignature") -> List[str]:
        """Provides human-readable diff points between two signatures."""
        diffs = []
        if self.args != other.args:
            diffs.append(f"positional arguments changed from {self.args} to {other.args}")
        if self.posonlyargs != other.posonlyargs:
            diffs.append(f"positional-only arguments changed from {self.posonlyargs} to {other.posonlyargs}")
        if self.defaults != other.defaults:
            diffs.append(f"default arguments changed from {self.defaults} to {other.defaults}")
        if self.kwonlyargs != other.kwonlyargs:
            diffs.append(f"keyword-only arguments changed from {self.kwonlyargs} to {other.kwonlyargs}")
        if self.kw_defaults != other.kw_defaults:
            diffs.append(f"keyword defaults changed from {self.kw_defaults} to {other.kw_defaults}")
        if self.vararg != other.vararg:
            diffs.append(f"vararg (*args) changed from {self.vararg} to {other.vararg}")
        if self.kwarg != other.kwarg:
            diffs.append(f"kwarg (**kwargs) changed from {self.kwarg} to {other.kwarg}")
        if self.is_async != other.is_async:
            diffs.append(f"async modifier changed from {self.is_async} to {other.is_async}")
        return diffs


def _dump_ast_expr(node: Optional[ast.AST]) -> Optional[str]:
    """Safely extracts stringified AST expression for default value comparison."""
    if node is None:
        return None
    try:
        return ast.unparse(node)
    except Exception:
        return ast.dump(node)


def extract_function_signatures(code_str: str) -> Dict[str, FunctionSignature]:
    """
    Parses source code into an AST and extracts signatures for all functions and methods.
    """
    tree = ast.parse(code_str)
    signatures: Dict[str, FunctionSignature] = {}

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn_name = node.name
            posonlyargs = [a.arg for a in getattr(node.args, "posonlyargs", [])]
            args = [a.arg for a in node.args.args]
            vararg = node.args.vararg.arg if node.args.vararg else None
            kwonlyargs = [a.arg for a in node.args.kwonlyargs]
            kw_defaults = [_dump_ast_expr(d) for d in node.args.kw_defaults]
            kwarg = node.args.kwarg.arg if node.args.kwarg else None
            defaults = [_dump_ast_expr(d) for d in node.args.defaults]

            signatures[fn_name] = FunctionSignature(
                name=fn_name,
                posonlyargs=posonlyargs,
                args=args,
                vararg=vararg,
                kwonlyargs=kwonlyargs,
                kw_defaults=kw_defaults,
                kwarg=kwarg,
                defaults=defaults,
                is_async=isinstance(node, ast.AsyncFunctionDef),
            )

    return signatures


def verify_ast_invariants(original_code: str, patched_code: str) -> Tuple[bool, str]:
    """
    Verifies that the patched code does not tamper with existing function signatures,
    remove existing functions, or manipulate default parameters to cheat tests.

    Returns:
        (is_valid, message): Boolean indicating invariant preservation and diagnostic message.
    """
    try:
        original_tree = ast.parse(original_code)
    except SyntaxError as e:
        return False, f"Original code contains syntax error: {e}"

    try:
        patched_tree = ast.parse(patched_code)
    except SyntaxError as e:
        return False, f"Patched code contains syntax error: {e}"

    original_sigs = extract_function_signatures(original_code)
    patched_sigs = extract_function_signatures(patched_code)

    for fn_name, orig_sig in original_sigs.items():
        # Public or core functions must not be dropped
        if fn_name not in patched_sigs:
            return False, f"Signature tampering detected: Function '{fn_name}' was removed in patched code."

        patched_sig = patched_sigs[fn_name]
        if orig_sig != patched_sig:
            diffs = orig_sig.describe_diff(patched_sig)
            diff_summary = "; ".join(diffs)
            return (
                False,
                f"Signature tampering detected in function '{fn_name}': {diff_summary}.",
            )

    return True, "AST signature invariants verified: No parameter or function tampering detected."


def extract_modified_files_from_diff(diff_text: str) -> List[str]:
    """Extracts target file paths modified in a standard unified git diff."""
    files: Set[str] = set()
    for line in diff_text.splitlines():
        git_match = re.match(r"^diff\s+--git\s+a/(.+?)\s+b/(.+?)$", line)
        if git_match:
            files.add(git_match.group(1).strip())
            files.add(git_match.group(2).strip())
            continue

        file_match = re.match(r"^(?:---|\+\+\+)\s+[ab]/(.+?)(?:\t.*|\s.*)?$", line)
        if file_match:
            path = file_match.group(1).strip()
            if path != "/dev/null":
                files.add(path)
    return sorted(list(files))


def verify_diff_targets(
    diff_text: str, allowed_targets: Optional[List[str]] = None
) -> Tuple[bool, str]:
    """
    Enforces workspace isolation by scanning the diff for forbidden paths.
    Rejects diffs modifying tests, test runners, or dependency configs.
    """
    if not diff_text or not diff_text.strip():
        return True, "No diff content provided; skipping diff path inspection."

    modified_files = extract_modified_files_from_diff(diff_text)
    if not modified_files:
        # Check if diff is malformed or empty
        return True, "Diff target verified (no target file headers found)."

    for file_path in modified_files:
        norm_path = file_path.replace("\\", "/").strip("/")

        # Check against forbidden paths
        for pattern in FORBIDDEN_DIFF_PATTERNS:
            if re.search(pattern, norm_path, re.IGNORECASE):
                return (
                    False,
                    f"Workspace isolation violation: diff touches protected harness/config target '{file_path}'.",
                )

        # If allowed_targets is specified, enforce strict whitelist
        if allowed_targets is not None:
            norm_allowed = [t.replace("\\", "/").strip("/") for t in allowed_targets]
            if norm_path not in norm_allowed:
                return (
                    False,
                    f"Workspace isolation violation: file '{file_path}' is not in allowed target files {allowed_targets}.",
                )

    return True, "Diff targets verified: diff modifies only authorized production files."


def run_out_of_band_evaluation(
    repo_root: str,
    target_file_rel: str,
    patched_code: str,
    diff_text: Optional[str] = None,
    test_paths: Optional[List[str]] = None,
    timeout_seconds: int = 30,
) -> Dict[str, Any]:
    """
    Orchestrates out-of-band evaluation:
    1. Verifies workspace isolation against the diff.
    2. Audits AST invariants between original and patched code.
    3. Provisions an ephemeral sandbox with clean test fixtures.
    4. Runs pytest in the sandbox and outputs structured JSON telemetry.
    """
    telemetry: Dict[str, Any] = {
        "harness_mode": "OUT_OF_BAND_ISOLATED",
        "diff_target_verified": False,
        "signature_tampering_detected": False,
        "evaluator_verdict": "FAILED",
    }

    # 1. Verify workspace isolation (diff check)
    if diff_text:
        diff_ok, diff_msg = verify_diff_targets(diff_text, allowed_targets=[target_file_rel])
        telemetry["diff_target_verified"] = diff_ok
        if not diff_ok:
            telemetry["error"] = diff_msg
            return telemetry
    else:
        # Validate that the target file itself is not a test/config target
        norm_target = target_file_rel.replace("\\", "/").strip("/")
        for pattern in FORBIDDEN_DIFF_PATTERNS:
            if re.search(pattern, norm_target, re.IGNORECASE):
                telemetry["diff_target_verified"] = False
                telemetry["error"] = f"Target file '{target_file_rel}' is a protected test/config file."
                return telemetry
        telemetry["diff_target_verified"] = True

    # 2. Verify AST invariants
    original_file_abs = os.path.join(repo_root, target_file_rel)
    original_code = ""
    if os.path.exists(original_file_abs):
        with open(original_file_abs, "r", encoding="utf-8") as f:
            original_code = f.read()

    if original_code:
        ast_ok, ast_msg = verify_ast_invariants(original_code, patched_code)
        if not ast_ok:
            telemetry["signature_tampering_detected"] = True
            telemetry["error"] = ast_msg
            return telemetry
    else:
        # If new file, ensure patched code has valid AST
        try:
            ast.parse(patched_code)
        except SyntaxError as e:
            telemetry["signature_tampering_detected"] = True
            telemetry["error"] = f"Syntax error in patched code: {e}"
            return telemetry

    telemetry["signature_tampering_detected"] = False

    # 3. Ephemeral Sandbox Provisioning & Out-Of-Band Subprocess Execution
    try:
        with tempfile.TemporaryDirectory(prefix="ghostdev_eval_sandbox_") as sandbox_dir:
            # Write patched production code inside isolated sandbox
            sandbox_target_path = os.path.join(sandbox_dir, target_file_rel)
            os.makedirs(os.path.dirname(sandbox_target_path), exist_ok=True)
            with open(sandbox_target_path, "w", encoding="utf-8") as f:
                f.write(patched_code)

            # Copy pristine test suites and test fixtures from origin repo
            copied_test_targets: List[str] = []

            # Check specified test_paths or default test locations
            candidate_test_sources = test_paths or ["tests", "test_sample_app.py"]
            for test_source in candidate_test_sources:
                src_abs = os.path.join(repo_root, test_source)
                dst_abs = os.path.join(sandbox_dir, test_source)
                if os.path.exists(src_abs):
                    if os.path.isdir(src_abs):
                        shutil.copytree(src_abs, dst_abs, dirs_exist_ok=True)
                    else:
                        os.makedirs(os.path.dirname(dst_abs), exist_ok=True)
                        shutil.copy2(src_abs, dst_abs)
                    copied_test_targets.append(test_source)

            # If no test files found, report failure
            if not copied_test_targets:
                telemetry["error"] = "No clean test fixtures found to mount into isolated sandbox."
                return telemetry

            # Prepare test command
            test_cmd = [sys.executable, "-m", "pytest"] + copied_test_targets + ["-v"]

            # Run test suite strictly inside the ephemeral sandbox
            env = os.environ.copy()
            # Ensure sandbox root is at front of PYTHONPATH
            env["PYTHONPATH"] = f"{sandbox_dir}{os.pathsep}{env.get('PYTHONPATH', '')}"

            proc = subprocess.run(
                test_cmd,
                cwd=sandbox_dir,
                env=env,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )

            if proc.returncode == 0:
                telemetry["evaluator_verdict"] = "PASSED"
            else:
                telemetry["evaluator_verdict"] = "FAILED"
                telemetry["test_output"] = (proc.stdout + "\n" + proc.stderr).strip()

    except subprocess.TimeoutExpired:
        telemetry["evaluator_verdict"] = "FAILED"
        telemetry["error"] = f"Evaluation timed out after {timeout_seconds} seconds."
    except Exception as exc:
        telemetry["evaluator_verdict"] = "FAILED"
        telemetry["error"] = f"Unexpected harness exception: {str(exc)}"

    return telemetry


if __name__ == "__main__":
    # Self-test / Standalone CLI verification execution
    base_dir = os.path.dirname(os.path.abspath(__file__))
    sample_app_path = "sample_app.py"
    target_abs = os.path.join(base_dir, sample_app_path)

    sample_code = ""
    if os.path.exists(target_abs):
        with open(target_abs, "r", encoding="utf-8") as f:
            sample_code = f.read()

    results = run_out_of_band_evaluation(
        repo_root=base_dir,
        target_file_rel=sample_app_path,
        patched_code=sample_code,
        test_paths=["test_sample_app.py", "tests"],
    )

    clean_telemetry = {
        "harness_mode": results.get("harness_mode", "OUT_OF_BAND_ISOLATED"),
        "diff_target_verified": results.get("diff_target_verified", False),
        "signature_tampering_detected": results.get("signature_tampering_detected", False),
        "evaluator_verdict": results.get("evaluator_verdict", "FAILED"),
    }

    print(json.dumps(clean_telemetry, indent=2))
