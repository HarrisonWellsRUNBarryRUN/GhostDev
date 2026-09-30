"""
Unit tests for GhostDev Checkpoint-Rollback-Agent (rollback_controller.py).
Validates ephemeral branch isolation, deterministic rollback, retry budget enforcement,
and context-pruning failure sanitization.
"""

import os
import sys
import shutil
import tempfile
import subprocess
import pytest

# Ensure parent directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rollback_controller import RollbackController


@pytest.fixture
def temp_git_repo():
    """Creates an isolated temporary git repository for testing rollback operations."""
    temp_dir = tempfile.mkdtemp(prefix="ghostdev_test_git_")
    
    # Initialize git repo
    subprocess.run(["git", "-C", temp_dir, "init"], check=True, capture_output=True)
    subprocess.run(["git", "-C", temp_dir, "config", "user.name", "GhostDev Tester"], check=True, capture_output=True)
    subprocess.run(["git", "-C", temp_dir, "config", "user.email", "tester@ghostdev.local"], check=True, capture_output=True)
    
    # Create initial file & commit
    initial_file = os.path.join(temp_dir, "sample.py")
    with open(initial_file, "w", encoding="utf-8") as f:
        f.write("def hello(): return 'world'\n")
    
    subprocess.run(["git", "-C", temp_dir, "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", temp_dir, "commit", "-m", "initial commit"], check=True, capture_output=True)
    
    yield temp_dir
    
    # Teardown
    shutil.rmtree(temp_dir, ignore_errors=True)


def test_create_checkpoint(temp_git_repo):
    controller = RollbackController(repo_path=temp_git_repo)
    sha = controller.create_checkpoint()
    
    assert sha is not None
    assert len(sha) == 40
    assert controller.checkpoint_sha == sha


def test_spawn_attempt_branch(temp_git_repo):
    controller = RollbackController(repo_path=temp_git_repo)
    controller.create_checkpoint()
    
    branch_name = controller.spawn_attempt_branch()
    assert branch_name.startswith("ghostdev/patch-attempt-")
    assert controller.get_current_branch() == branch_name
    assert controller.attempt_count == 1


def test_deterministic_rollback_cleans_workspace(temp_git_repo):
    controller = RollbackController(repo_path=temp_git_repo)
    controller.create_checkpoint()
    
    attempt_branch = controller.spawn_attempt_branch()
    
    # Simulate toxic patch: write corrupted changes & create untracked artifacts
    sample_file = os.path.join(temp_git_repo, "sample.py")
    with open(sample_file, "w", encoding="utf-8") as f:
        f.write("corrupted code syntax error !!!\n")
        
    polluted_artifact = os.path.join(temp_git_repo, "garbage_artifact.tmp")
    with open(polluted_artifact, "w", encoding="utf-8") as f:
        f.write("pollution")

    # Verify pollution exists
    assert os.path.exists(polluted_artifact)
    with open(sample_file, "r") as f:
        assert "corrupted" in f.read()

    # Execute deterministic rollback
    telemetry = controller.rollback_to_checkpoint()

    assert telemetry["rollback_controller"] == "ACTIVE"
    assert telemetry["state_status"] == "PRISTINE_RESTORED"
    assert telemetry["context_pollution_prevented"] is True

    # Verify workspace is pristine again
    assert not os.path.exists(polluted_artifact)
    with open(sample_file, "r") as f:
        assert "def hello(): return 'world'" in f.read()

    # Verify attempt branch was deleted and base branch restored
    code, stdout, _ = controller._run_git(["branch", "--list", attempt_branch])
    assert attempt_branch not in stdout


def test_retry_budget_enforcement(temp_git_repo):
    controller = RollbackController(repo_path=temp_git_repo, max_attempts=2)
    controller.create_checkpoint()
    
    controller.spawn_attempt_branch()
    controller.rollback_to_checkpoint()
    
    controller.spawn_attempt_branch()
    controller.rollback_to_checkpoint()
    
    # 3rd attempt must exceed max_attempts=2
    with pytest.raises(RuntimeError, match="Retry budget exhausted"):
        controller.spawn_attempt_branch()


def test_commit_successful_patch(temp_git_repo):
    controller = RollbackController(repo_path=temp_git_repo)
    controller.create_checkpoint()
    
    attempt_branch = controller.spawn_attempt_branch()
    
    sample_file = os.path.join(temp_git_repo, "sample.py")
    with open(sample_file, "w", encoding="utf-8") as f:
        f.write("def hello(): return 'fixed_world'\n")
        
    telemetry = controller.commit_successful_patch("fix: resolve greeting")
    
    assert telemetry["state_status"] == "COMMITTED"
    assert telemetry["context_pollution_prevented"] is True
    
    # Verify commit exists
    code, stdout, _ = controller._run_git(["log", "-1", "--pretty=%B"])
    assert "fix: resolve greeting" in stdout


def test_sanitize_failure_context():
    controller = RollbackController()
    
    raw_pytest_output = """
==================================== FAILURES ====================================
___________________________ test_divide_numbers_zero ___________________________

    def test_divide_numbers_zero():
>       assert divide_numbers(10, 0) is None
E       AssertionError: assert 0 is None
E       sample_app.py:15: in divide_numbers

test_sample_app.py:12: AssertionError
=========================== short test summary info ============================
FAILED test_sample_app.py::test_divide_numbers_zero - AssertionError: assert 0 is None
"""
    
    sanitized = controller.sanitize_failure_context(raw_pytest_output)
    
    assert sanitized["context_pollution_prevented"] is True
    assert "AssertionError: assert 0 is None" in sanitized["failing_assertion"]
    assert "sample_app.py:15: in divide_numbers" in sanitized["offending_location"]
    assert "sample_app.py:15" in sanitized["sanitized_summary"]
