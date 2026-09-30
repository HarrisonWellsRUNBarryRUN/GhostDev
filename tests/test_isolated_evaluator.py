"""
Unit tests for GhostDev Isolated-Harness-Agent (isolated_evaluator.py).
Validates workspace isolation, AST signature invariant checks, and ephemeral sandbox execution.
"""

import os
import sys
import pytest

from isolated_evaluator import (
    extract_function_signatures,
    verify_ast_invariants,
    verify_diff_targets,
    run_out_of_band_evaluation,
)

ORIGINAL_CODE = '''
def divide_numbers(a: float, b: float):
    """Divides number a by number b."""
    return a / b

def add_numbers(a: float, b: float) -> float:
    """Returns the sum of a and b."""
    return a + b
'''

CLEAN_PATCH = '''
def divide_numbers(a: float, b: float):
    """Divides number a by number b safely."""
    try:
        val_a = float(a)
        val_b = float(b)
        if val_b == 0.0:
            return None
        return val_a / val_b
    except (ZeroDivisionError, OverflowError, TypeError, ValueError):
        return None

def add_numbers(a: float, b: float) -> float:
    """Returns the sum of a and b."""
    return a + b
'''

TAMPERED_DEFAULT_ARG_PATCH = '''
def divide_numbers(a: float, b: float = 1.0):
    """Hacked default argument b=1.0 to bypass zero division checks."""
    return a / b

def add_numbers(a: float, b: float) -> float:
    return a + b
'''

TAMPERED_MISSING_FUNC_PATCH = '''
def add_numbers(a: float, b: float) -> float:
    return a + b
'''

TAMPERED_RENAMED_ARG_PATCH = '''
def divide_numbers(x: float, y: float):
    return x / y

def add_numbers(a: float, b: float) -> float:
    return a + b
'''


def test_ast_invariant_clean_patch():
    is_valid, msg = verify_ast_invariants(ORIGINAL_CODE, CLEAN_PATCH)
    assert is_valid is True
    assert "No parameter or function tampering detected" in msg


def test_ast_invariant_detects_default_arg_manipulation():
    is_valid, msg = verify_ast_invariants(ORIGINAL_CODE, TAMPERED_DEFAULT_ARG_PATCH)
    assert is_valid is False
    assert "Signature tampering detected in function 'divide_numbers'" in msg
    assert "default arguments changed" in msg


def test_ast_invariant_detects_missing_function():
    is_valid, msg = verify_ast_invariants(ORIGINAL_CODE, TAMPERED_MISSING_FUNC_PATCH)
    assert is_valid is False
    assert "Function 'divide_numbers' was removed" in msg


def test_ast_invariant_detects_renamed_params():
    is_valid, msg = verify_ast_invariants(ORIGINAL_CODE, TAMPERED_RENAMED_ARG_PATCH)
    assert is_valid is False
    assert "positional arguments changed" in msg


def test_diff_isolation_clean_diff():
    diff = """diff --git a/sample_app.py b/sample_app.py
--- a/sample_app.py
+++ b/sample_app.py
@@ -10,3 +10,5 @@
+    if b == 0:
+        return None
"""
    is_valid, msg = verify_diff_targets(diff, allowed_targets=["sample_app.py"])
    assert is_valid is True


def test_diff_isolation_rejects_test_modification():
    diff = """diff --git a/tests/test_sample_app.py b/tests/test_sample_app.py
--- a/tests/test_sample_app.py
+++ b/tests/test_sample_app.py
@@ -10,3 +10,3 @@
-    assert divide_numbers(10, 0) is None
+    assert True
"""
    is_valid, msg = verify_diff_targets(diff, allowed_targets=["sample_app.py"])
    assert is_valid is False
    assert "Workspace isolation violation" in msg


def test_diff_isolation_rejects_conftest_modification():
    diff = """diff --git a/conftest.py b/conftest.py
--- a/conftest.py
+++ b/conftest.py
@@ -1,1 +1,1 @@
+# fixture hack
"""
    is_valid, msg = verify_diff_targets(diff, allowed_targets=["sample_app.py"])
    assert is_valid is False
    assert "touches protected harness/config target" in msg


def test_run_out_of_band_evaluation_passed():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results = run_out_of_band_evaluation(
        repo_root=repo_root,
        target_file_rel="sample_app.py",
        patched_code=CLEAN_PATCH,
        test_paths=["test_sample_app.py"],
    )

    assert results["harness_mode"] == "OUT_OF_BAND_ISOLATED"
    assert results["diff_target_verified"] is True
    assert results["signature_tampering_detected"] is False
    assert results["evaluator_verdict"] == "PASSED"


def test_run_out_of_band_evaluation_tampered_fails():
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    results = run_out_of_band_evaluation(
        repo_root=repo_root,
        target_file_rel="sample_app.py",
        patched_code=TAMPERED_DEFAULT_ARG_PATCH,
        test_paths=["test_sample_app.py"],
    )

    assert results["harness_mode"] == "OUT_OF_BAND_ISOLATED"
    assert results["diff_target_verified"] is True
    assert results["signature_tampering_detected"] is True
    assert results["evaluator_verdict"] == "FAILED"
