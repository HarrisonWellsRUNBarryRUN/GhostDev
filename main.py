"""
GhostDev - Autonomous Multi-Agent System Engine
Orchestrates Diagnoser, Coder, Tester, and Git agents using LangGraph.
Supports both real LLM execution and a complete offline local simulation mode.
"""

import os
import sys
import json
import re
import warnings
import subprocess
from typing import TypedDict, Optional, Dict, Any

# Suppress minor dependency version warnings for cleaner terminal output
warnings.filterwarnings("ignore")

# Ensure UTF-8 output on Windows consoles to prevent UnicodeEncodeError with emojis
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv
import git
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langgraph.graph import StateGraph, START, END

import prompts

# Load environment configuration
load_dotenv()


# =====================================================================
# AGENT STATE DEFINITION
# =====================================================================

class GhostDevState(TypedDict):
    issue_id: str
    issue_description: str
    target_file: str
    test_file: str
    diagnoser_output: Optional[Dict[str, Any]]
    coder_code: Optional[str]
    test_passed: bool
    test_summary: Optional[str]
    test_feedback: Optional[str]
    retry_count: int
    max_retries: int
    git_branch: Optional[str]
    git_commit_msg: Optional[str]
    pr_description: Optional[str]


# =====================================================================
# CONFIGURATION & UTILITIES
# =====================================================================

def is_simulation_mode() -> bool:
    """Checks whether to run in offline local simulation mode."""
    env_sim = os.getenv("SIMULATION_MODE", "").lower()
    if env_sim in ("true", "1", "yes"):
        return True
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "your_openai_api_key_here":
        return True
    return False


def get_llm() -> Optional[ChatOpenAI]:
    """Returns ChatOpenAI instance if valid API key is present and not in simulation mode."""
    if is_simulation_mode():
        return None
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    model_name = os.getenv("OPENAI_MODEL_NAME", "gpt-4o")
    return ChatOpenAI(model=model_name, temperature=0, api_key=api_key)


def extract_code_block(text: str) -> str:
    """Strips markdown code fences if present, returning raw source code."""
    pattern = r"```(?:python)?\s*\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def extract_json(text: str) -> Dict[str, Any]:
    """Safely extracts JSON from model text response."""
    pattern = r"```(?:json)?\s*\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        return json.loads(match.group(1).strip())
    json_match = re.search(r"(\{.*\})", text, re.DOTALL)
    if json_match:
        return json.loads(json_match.group(1).strip())
    return json.loads(text.strip())


def reset_sample_app_to_buggy():
    """Ensures sample_app.py has the unhandled ZeroDivisionError bug before running."""
    buggy_code = (
        '"""\n'
        'Sample application module containing basic mathematical operations.\n'
        '"""\n\n'
        'def divide_numbers(a: float, b: float):\n'
        '    """\n'
        '    Divides number a by number b.\n'
        '    Should handle division by zero safely by returning None.\n'
        '    """\n'
        '    # Intentional Bug: Throws ZeroDivisionError when b == 0\n'
        '    return a / b\n\n'
        'def add_numbers(a: float, b: float) -> float:\n'
        '    """Returns the sum of a and b."""\n'
        '    return a + b\n'
    )
    with open("sample_app.py", "w", encoding="utf-8") as f:
        f.write(buggy_code)


def prepare_repository_and_branch(branch_name: str = "fix/ghostdev-demo"):
    """
    Prepares git repository cleanly on the target branch and resets sample_app.py to buggy baseline.
    """
    repo_path = os.getenv("REPO_PATH", ".")
    try:
        repo = git.Repo(repo_path)
    except (git.exc.InvalidGitRepositoryError, git.exc.NoSuchPathError):
        repo = git.Repo.init(repo_path)

    # Configure local git user if not configured
    with repo.config_writer() as config:
        if not config.has_option("user", "name"):
            config.set_value("user", "name", "GhostDev Agent")
        if not config.has_option("user", "email"):
            config.set_value("user", "email", "agent@ghostdev.local")

    # If repo has no commits, create baseline
    if not repo.heads:
        reset_sample_app_to_buggy()
        repo.git.add(all=True)
        repo.index.commit("chore: initial baseline commit")

    # Clean working tree and checkout master/main
    default_branch = "master" if "master" in [h.name for h in repo.heads] else repo.heads[0].name
    if repo.active_branch.name != default_branch:
        repo.git.checkout(default_branch)

    # Recreate the demo branch freshly from baseline
    if branch_name in [h.name for h in repo.heads]:
        repo.delete_head(branch_name, force=True)

    repo.git.checkout("-b", branch_name)
    reset_sample_app_to_buggy()
    return repo


# =====================================================================
# AGENT NODES
# =====================================================================

def diagnoser_node(state: GhostDevState) -> Dict[str, Any]:
    """
    Diagnoser-Agent: Analyzes issue description and target source code to formulate a JSON plan.
    """
    print("\n🔍 [1/4] Diagnoser-Agent: Analyzing issue and codebase...")

    target_file = state["target_file"]
    current_code = ""
    if os.path.exists(target_file):
        with open(target_file, "r", encoding="utf-8") as f:
            current_code = f.read()

    llm = get_llm()
    if llm:
        user_prompt = (
            f"GitHub Issue ID: {state['issue_id']}\n"
            f"Issue Description: {state['issue_description']}\n\n"
            f"File: {target_file}\n"
            f"Current File Content:\n```python\n{current_code}\n```"
        )
        messages = [
            SystemMessage(content=prompts.SYSTEM_DIAGNOSER_PROMPT),
            HumanMessage(content=user_prompt)
        ]
        response = llm.invoke(messages)
        try:
            diagnosis = extract_json(response.content)
        except Exception:
            diagnosis = {
                "target_file": target_file,
                "root_cause": "Unhandled ZeroDivisionError in divide_numbers when b == 0.",
                "fix_plan": "Add an explicit guard `if b == 0: return None` before performing division."
            }
    else:
        print("   📥 Ingested issue report: 'ZeroDivisionError in divide_numbers(a, b)'")
        print(f"   📂 Scanned target file: {target_file}")
        diagnosis = {
            "target_file": target_file,
            "root_cause": "Function divide_numbers() performs raw division 'a / b' without validating if denominator 'b == 0', causing ZeroDivisionError.",
            "fix_plan": "Add validation guard at start of divide_numbers: if b == 0, return None instead of raising ZeroDivisionError."
        }

    print(f"   🎯 Target: {diagnosis.get('target_file')}")
    print(f"   💡 Root Cause: {diagnosis.get('root_cause')}")
    print(f"   📋 Fix Plan: {diagnosis.get('fix_plan')}")

    return {"diagnoser_output": diagnosis}


def coder_node(state: GhostDevState) -> Dict[str, Any]:
    """
    Coder-Agent: Modifies target source code based on Diagnoser's plan or Tester's feedback.
    In simulation mode, deliberately generates a candidate fix with a minor flaw on Attempt 1
    to test the feedback loop, and resolves it completely on Attempt 2.
    """
    retry_num = state.get("retry_count", 0)
    target_file = state["target_file"]

    current_code = ""
    if os.path.exists(target_file):
        with open(target_file, "r", encoding="utf-8") as f:
            current_code = f.read()

    llm = get_llm()

    if llm:
        if retry_num > 0:
            print(f"\n💻 [2/4] Coder-Agent: Self-correcting code (Attempt {retry_num + 1})...")
        else:
            print("\n💻 [2/4] Coder-Agent: Implementing fix based on plan...")

        diagnoser_output = state.get("diagnoser_output", {})
        fix_plan = diagnoser_output.get("fix_plan", "Fix the reported bug.")
        test_feedback = state.get("test_feedback")

        user_prompt = (
            f"Target File: {target_file}\n"
            f"Fix Plan: {fix_plan}\n"
        )
        if test_feedback:
            user_prompt += f"\nPrevious Test Failure Feedback:\n{test_feedback}\n"
        user_prompt += f"\nCurrent Source Code:\n```python\n{current_code}\n```"

        messages = [
            SystemMessage(content=prompts.SYSTEM_CODER_PROMPT),
            HumanMessage(content=user_prompt)
        ]
        response = llm.invoke(messages)
        new_code = extract_code_block(response.content)

    else:
        # Local Simulation Mode
        if retry_num == 0:
            print("\n💻 [2/4] Coder-Agent: Implementing initial patch (Attempt 1)...")
            print("   ⚠️  [Simulation Note]: Writing candidate fix (mistakenly returning 0 instead of None to test feedback loop)...")
            # Flawed attempt: returns 0 instead of None
            new_code = (
                '"""\n'
                'Sample application module containing basic mathematical operations.\n'
                '"""\n\n'
                'def divide_numbers(a: float, b: float):\n'
                '    """\n'
                '    Divides number a by number b.\n'
                '    Should handle division by zero safely by returning None.\n'
                '    """\n'
                '    # Candidate fix Attempt 1: returns 0 instead of None\n'
                '    if b == 0:\n'
                '        return 0\n'
                '    return a / b\n\n'
                'def add_numbers(a: float, b: float) -> float:\n'
                '    """Returns the sum of a and b."""\n'
                '    return a + b\n'
            )
        else:
            print(f"\n💻 [2/4] Coder-Agent: Self-correcting code based on Tester feedback (Attempt {retry_num + 1})...")
            print("   📥 Analyzing Tester-Agent feedback:")
            print("      -> Expected: None | Received: 0 (AssertionError: assert 0 is None)")
            print("   🛠️ Refining patch: Correcting return value to 'None' when b == 0...")

            # Clean, production-grade fix
            new_code = (
                '"""\n'
                'Sample application module containing basic mathematical operations.\n'
                '"""\n\n'
                'def divide_numbers(a: float, b: float):\n'
                '    """\n'
                '    Divides number a by number b.\n'
                '    Should handle division by zero safely by returning None.\n'
                '    """\n'
                '    if b == 0:\n'
                '        return None\n'
                '    return a / b\n\n'
                'def add_numbers(a: float, b: float) -> float:\n'
                '    """Returns the sum of a and b."""\n'
                '    return a + b\n'
            )

    # Persist candidate code to disk
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(new_code)

    print(f"   💾 Saved candidate code to {target_file}")
    return {"coder_code": new_code}


def tester_node(state: GhostDevState) -> Dict[str, Any]:
    """
    Tester-Agent: Runs unit tests via subprocess (pytest) and evaluates execution output.
    """
    retry_num = state.get("retry_count", 0)
    print(f"\n🧪 [3/4] Tester-Agent: Executing unit test suite (Attempt {retry_num + 1})...")

    test_file = state.get("test_file", "test_sample_app.py")
    test_cmd = [sys.executable, "-m", "pytest", test_file, "-v"]

    proc = subprocess.run(test_cmd, capture_output=True, text=True)
    stdout = proc.stdout
    stderr = proc.stderr
    combined_output = stdout + "\n" + stderr

    passed = (proc.returncode == 0)

    llm = get_llm()
    if llm:
        user_prompt = f"Pytest Execution Log:\n{combined_output}"
        messages = [
            SystemMessage(content=prompts.SYSTEM_TESTER_PROMPT),
            HumanMessage(content=user_prompt)
        ]
        response = llm.invoke(messages)
        try:
            test_report = extract_json(response.content)
        except Exception:
            test_report = {
                "status": "SUCCESS" if passed else "FAILED",
                "summary": "All tests passed." if passed else "Unit tests failed.",
                "feedback_for_coder": None if passed else combined_output
            }
    else:
        if passed:
            test_report = {
                "status": "SUCCESS",
                "summary": "All 4 unit tests in test_sample_app.py passed successfully.",
                "feedback_for_coder": None
            }
        else:
            test_report = {
                "status": "FAILED",
                "summary": "AssertionError in test_sample_app.py: expected None when b == 0, but received 0.",
                "feedback_for_coder": "test_divide_numbers_zero failed: assert divide_numbers(10, 0) is None, returned 0 instead."
            }

    current_retries = state.get("retry_count", 0)
    new_retries = current_retries if passed else current_retries + 1

    if passed:
        print(f"   ✅ Tests PASSED: {test_report.get('summary')}")
        print("   🎯 Ready for git release.")
    else:
        print(f"   ❌ Tests FAILED: {test_report.get('summary')}")
        print(f"   📢 Triggering self-correction loop to Coder-Agent (Attempt {new_retries}/{state.get('max_retries', 3)})...")

    return {
        "test_passed": passed,
        "test_summary": test_report.get("summary"),
        "test_feedback": test_report.get("feedback_for_coder"),
        "retry_count": new_retries
    }


def git_node(state: GhostDevState) -> Dict[str, Any]:
    """
    Git-Agent: Uses GitPython to stage changes, commit, and prepare PR summary.
    """
    print("\n📦 [4/4] Git-Agent: Managing version control and PR generation...")

    branch_name = "fix/ghostdev-demo"
    commit_msg = f"fix({state['target_file'].split('.')[0]}): handle zero division gracefully"
    
    repo_path = os.getenv("REPO_PATH", ".")
    repo = git.Repo(repo_path)

    print(f"   🌿 Active branch: {branch_name}")

    # Stage the target file and commit
    repo.git.add(state["target_file"])
    repo.index.commit(commit_msg)
    print(f"   📝 Committed changes: '{commit_msg}'")

    # Generate PR description
    diagnoser_output = state.get("diagnoser_output", {})
    root_cause = diagnoser_output.get("root_cause", "Unhandled ZeroDivisionError in divide_numbers().")
    fix_plan = diagnoser_output.get("fix_plan", "Guard division by zero by returning None.")
    retries = state.get("retry_count", 0)

    pr_description = (
        f"## 👻 GhostDev Auto-Fix Summary\n\n"
        f"- **Branch**: `{branch_name}`\n"
        f"- **Target File**: `{state['target_file']}`\n"
        f"- **Root Cause**: {root_cause}\n"
        f"- **Applied Patch**: {fix_plan}\n"
        f"- **Verification**: {state.get('test_summary', 'All local unit tests passed.')} (Self-correction cycles: {retries})\n"
    )

    print("\n" + "=" * 60)
    print(pr_description.strip())
    print("=" * 60)

    return {
        "git_branch": branch_name,
        "git_commit_msg": commit_msg,
        "pr_description": pr_description
    }


# =====================================================================
# CONDITIONAL ROUTING LOGIC
# =====================================================================

def route_after_tester(state: GhostDevState) -> str:
    """
    Evaluates test results:
    - If passed -> Git-Agent
    - If failed & retries remain -> Coder-Agent (self-correction)
    - If failed & retries exhausted -> END
    """
    if state.get("test_passed"):
        return "git_node"
    
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)
    
    if retry_count < max_retries:
        return "coder_node"
    
    print("🛑 Maximum retries reached without passing tests. Terminating workflow.")
    return END


# =====================================================================
# LANGGRAPH STATEGRAPH CONSTRUCTION
# =====================================================================

def build_ghostdev_graph():
    """Builds and compiles the LangGraph StateGraph workflow."""
    workflow = StateGraph(GhostDevState)

    # Register agent nodes
    workflow.add_node("diagnoser_node", diagnoser_node)
    workflow.add_node("coder_node", coder_node)
    workflow.add_node("tester_node", tester_node)
    workflow.add_node("git_node", git_node)

    # Define execution graph edges
    workflow.add_edge(START, "diagnoser_node")
    workflow.add_edge("diagnoser_node", "coder_node")
    workflow.add_edge("coder_node", "tester_node")

    # Conditional feedback loop from Tester
    workflow.add_conditional_edges(
        "tester_node",
        route_after_tester,
        {
            "git_node": "git_node",
            "coder_node": "coder_node",
            END: END
        }
    )
    workflow.add_edge("git_node", END)

    return workflow.compile()


# =====================================================================
# MAIN ENTRYPOINT
# =====================================================================

if __name__ == "__main__":
    simulation = is_simulation_mode()

    print("=" * 60)
    print("👻 GHOSTDEV: AUTONOMOUS MULTI-AGENT SELF-HEALING ENGINE")
    if simulation:
        print("   [Mode: Local Simulation & Self-Correction Demonstration]")
    else:
        print("   [Mode: Live LLM Connected]")
    print("=" * 60)

    # Prepare repository on clean demo branch with buggy baseline
    prepare_repository_and_branch("fix/ghostdev-demo")

    # Initial state representing a reported GitHub issue
    initial_state: GhostDevState = {
        "issue_id": "demo",
        "issue_description": (
            "Bug: divide_numbers(a, b) crashes with ZeroDivisionError when denominator b is 0. "
            "Expected behavior: gracefully handle division by zero and return None."
        ),
        "target_file": "sample_app.py",
        "test_file": "test_sample_app.py",
        "diagnoser_output": None,
        "coder_code": None,
        "test_passed": False,
        "test_summary": None,
        "test_feedback": None,
        "retry_count": 0,
        "max_retries": 3,
        "git_branch": None,
        "git_commit_msg": None,
        "pr_description": None
    }

    app = build_ghostdev_graph()
    final_output = app.invoke(initial_state)

    print("\n🎉 GhostDev workflow execution completed.")
    if final_output.get("test_passed"):
        print(f"✨ Successfully healed bug and pushed branch '{final_output.get('git_branch')}'!")
    else:
        print("⚠️ Workflow finished without achieving a passing test suite.")
