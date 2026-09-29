"""
GhostDev - Autonomous Multi-Agent System Engine
Orchestrates Diagnoser, Coder, Tester, and Git agents using LangGraph.
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
# LLM HELPER & PARSING UTILITIES
# =====================================================================

def get_llm() -> Optional[ChatOpenAI]:
    """Returns ChatOpenAI instance if a valid API key is present, else None."""
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key or api_key == "your_openai_api_key_here":
        return None
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

    user_prompt = (
        f"GitHub Issue ID: {state['issue_id']}\n"
        f"Issue Description: {state['issue_description']}\n\n"
        f"File: {target_file}\n"
        f"Current File Content:\n```python\n{current_code}\n```"
    )

    llm = get_llm()
    if llm:
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
        print("   ℹ️  (OpenAI key placeholder detected; using deterministic diagnosis for demo)")
        diagnosis = {
            "target_file": target_file,
            "root_cause": "The divide_numbers function raises ZeroDivisionError when b == 0 instead of returning None gracefully.",
            "fix_plan": "Add validation `if b == 0: return None` at the start of divide_numbers before returning a / b."
        }

    print(f"   🎯 Target: {diagnosis.get('target_file')}")
    print(f"   💡 Root Cause: {diagnosis.get('root_cause')}")
    print(f"   📋 Fix Plan: {diagnosis.get('fix_plan')}")

    return {"diagnoser_output": diagnosis}


def coder_node(state: GhostDevState) -> Dict[str, Any]:
    """
    Coder-Agent: Modifies target source code based on Diagnoser's plan or Tester's feedback.
    """
    retry_num = state.get("retry_count", 0)
    if retry_num > 0:
        print(f"\n💻 [2/4] Coder-Agent: Self-correcting code (Attempt {retry_num + 1})...")
    else:
        print("\n💻 [2/4] Coder-Agent: Implementing fix based on plan...")

    target_file = state["target_file"]
    current_code = ""
    if os.path.exists(target_file):
        with open(target_file, "r", encoding="utf-8") as f:
            current_code = f.read()

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

    llm = get_llm()
    if llm:
        messages = [
            SystemMessage(content=prompts.SYSTEM_CODER_PROMPT),
            HumanMessage(content=user_prompt)
        ]
        response = llm.invoke(messages)
        new_code = extract_code_block(response.content)
    else:
        # High-quality deterministic resolution for demonstration
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

    # Persist the modified code to disk
    with open(target_file, "w", encoding="utf-8") as f:
        f.write(new_code)

    print(f"   💾 Saved updated code to {target_file}")
    return {"coder_code": new_code}


def tester_node(state: GhostDevState) -> Dict[str, Any]:
    """
    Tester-Agent: Runs unit tests via subprocess (pytest) and parses execution output.
    """
    print("\n🧪 [3/4] Tester-Agent: Executing unit test suite...")

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
                "summary": "Tests passed." if passed else "Tests failed.",
                "feedback_for_coder": None if passed else combined_output
            }
    else:
        test_report = {
            "status": "SUCCESS" if passed else "FAILED",
            "summary": "All pytest assertions passed successfully." if passed else "Pytest failed on assertion.",
            "feedback_for_coder": None if passed else combined_output
        }

    current_retries = state.get("retry_count", 0)
    new_retries = current_retries if passed else current_retries + 1

    if passed:
        print(f"   ✅ Tests PASSED: {test_report.get('summary')}")
    else:
        print(f"   ❌ Tests FAILED: {test_report.get('summary')}")
        print(f"   ⚠️  Retry count: {new_retries}/{state.get('max_retries', 3)}")

    return {
        "test_passed": passed,
        "test_summary": test_report.get("summary"),
        "test_feedback": test_report.get("feedback_for_coder"),
        "retry_count": new_retries
    }


def git_node(state: GhostDevState) -> Dict[str, Any]:
    """
    Git-Agent: Uses GitPython to create a fix branch, commit changes, and prepare PR summary.
    """
    print("\n📦 [4/4] Git-Agent: Managing version control and PR generation...")

    issue_id = state.get("issue_id", "101")
    branch_name = f"fix/ghostdev-{issue_id}"
    commit_msg = f"fix({state['target_file'].split('.')[0]}): resolve zero division error"
    
    # Initialize or load git repository safely
    repo_path = os.getenv("REPO_PATH", ".")
    try:
        repo = git.Repo(repo_path)
    except (git.exc.InvalidGitRepositoryError, git.exc.NoSuchPathError):
        print("   📁 Initializing new local git repository...")
        repo = git.Repo.init(repo_path)

    # Configure local git user if not present
    with repo.config_writer() as config:
        if not config.has_option("user", "name"):
            config.set_value("user", "name", "GhostDev Agent")
        if not config.has_option("user", "email"):
            config.set_value("user", "email", "agent@ghostdev.local")

    # If repository has no commits, create a baseline commit first
    if not repo.heads:
        repo.git.add(all=True)
        repo.index.commit("chore: initial commit before GhostDev auto-fix")

    # Create or checkout feature branch
    existing_branches = [h.name for h in repo.heads]
    if branch_name in existing_branches:
        repo.git.checkout(branch_name)
    else:
        repo.git.checkout("-b", branch_name)
    print(f"   🌿 Checked out branch: {branch_name}")

    # Stage the modified file and commit
    repo.git.add(state["target_file"])
    repo.index.commit(commit_msg)
    print(f"   📝 Committed changes: '{commit_msg}'")

    # Generate PR description
    diagnoser_output = state.get("diagnoser_output", {})
    root_cause = diagnoser_output.get("root_cause", "ZeroDivisionError unhandled when denominator is zero.")
    fix_plan = diagnoser_output.get("fix_plan", "Added zero-division safety check.")

    pr_description = (
        f"## 👻 GhostDev Auto-Fix Summary\n"
        f"- **Issue ID**: #{issue_id}\n"
        f"- **Target File**: `{state['target_file']}`\n"
        f"- **Root Cause**: {root_cause}\n"
        f"- **Applied Patch**: {fix_plan}\n"
        f"- **Verification**: {state.get('test_summary', 'All local unit tests passed.')}\n"
    )

    print("\n" + "=" * 60)
    print(pr_description)
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
        print(f"🔄 Routing back to Coder-Agent for self-correction (Attempt {retry_count + 1}/{max_retries})...")
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
    print("=" * 60)
    print("👻 GHOSTDEV: AUTONOMOUS MULTI-AGENT SELF-HEALING ENGINE")
    print("=" * 60)

    # Initial state representing a reported GitHub issue
    initial_state: GhostDevState = {
        "issue_id": "42",
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
        print(f"✨ Successfully healed bug and prepared branch {final_output.get('git_branch')}!")
    else:
        print("⚠️ Workflow finished without achieving a passing test suite.")
