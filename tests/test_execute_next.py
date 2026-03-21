import json

from forge.cli import ForgeCLI
from forge.executor import Executor
from forge.paths import Paths

from tests.forge_test_project import configure_project, forge_block


def _two_milestones_body():
    return f"""
# Milestones

## Milestone 1: A
- **Objective**: A objective
- **Scope**: A scope
- **Validation**: A validation
{forge_block("FORGE_M1")}

## Milestone 2: B
- **Objective**: B objective
- **Scope**: B scope
- **Validation**: B validation
{forge_block("FORGE_M2")}
"""


def _write_dependency_milestones(path, prereq_incomplete=False):
    prereq_obj = "Prereq objective"
    # Scope/validation must be non-empty for parser; omit forge block when "incomplete".
    if prereq_incomplete:
        prereq_scope = "Prereq has no Forge Actions yet (incomplete)."
        prereq_val = "Execution cannot succeed until actions are defined."
    else:
        prereq_scope = "Prereq scope"
        prereq_val = "Prereq validation"
    prereq_forge = "" if prereq_incomplete else forge_block("FORGE_PREREQ")

    path.write_text(
        f"""
# Milestones

## Milestone 1: Prerequisite
- **Objective**: {prereq_obj}
- **Scope**: {prereq_scope}
- **Validation**: {prereq_val}
{prereq_forge}

## Milestone 2: Dependent
- **Depends On**: 1
- **Objective**: Dependent objective
- **Scope**: Dependent scope
- **Validation**: Dependent validation
{forge_block("FORGE_DEP")}
"""
    )


def test_execute_next_executes_first_not_started(tmp_path):
    configure_project(tmp_path, _two_milestones_body())
    ForgeCLI.milestone_sync_state()

    result = Executor.execute_next()
    assert result["outcome"] == "complete"
    assert result["milestone_id"] == 1

    state = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert state["1"]["status"] == "completed"
    assert state["1"]["attempts"] == 1
    assert state["2"]["status"] == "not_started"

    assert (Paths.SYSTEM_DIR / "results" / "milestone_1.json").exists()


def test_execute_next_prefers_retry_pending(tmp_path):
    configure_project(tmp_path, _two_milestones_body())
    ForgeCLI.milestone_sync_state()

    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    state_file.write_text(
        json.dumps(
            {"1": {"status": "retry_pending", "attempts": 1}, "2": {"status": "not_started", "attempts": 0}},
            indent=4,
        )
    )

    result = Executor.execute_next()
    assert result["outcome"] == "complete"
    assert result["milestone_id"] == 1

    state = json.loads(state_file.read_text())
    assert state["1"]["status"] == "completed"
    assert state["1"]["attempts"] == 2
    assert state["2"]["status"] == "not_started"


def test_execute_next_returns_complete_when_all_done(tmp_path):
    configure_project(tmp_path, _two_milestones_body())
    ForgeCLI.milestone_sync_state()

    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    state_file.write_text(
        json.dumps(
            {
                "1": {"status": "completed", "attempts": 2},
                "2": {"status": "completed", "attempts": 1},
            },
            indent=4,
        )
    )

    result = Executor.execute_next()
    assert result["outcome"] == "complete"


def test_execute_next_returns_in_progress_when_active_and_nothing_else(tmp_path):
    configure_project(tmp_path, _two_milestones_body())
    ForgeCLI.milestone_sync_state()

    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    state_file.write_text(
        json.dumps(
            {
                "1": {"status": "in_progress", "attempts": 1},
                "2": {"status": "in_progress", "attempts": 0},
            },
            indent=4,
        )
    )

    result = Executor.execute_next()
    assert result["outcome"] == "in_progress"


def test_execute_next_returns_blocked_when_prereq_failed(tmp_path):
    Paths.refresh(tmp_path)
    Paths.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    Paths.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.REQUIREMENTS_FILE.write_text("# Requirements\n\n## Overview\n\n", encoding="utf-8")
    Paths.ARCHITECTURE_FILE.write_text("# Architecture\n\n## Design\n\n", encoding="utf-8")
    Paths.DECISIONS_FILE.write_text("# Decisions\n\n## Log\n\n", encoding="utf-8")
    Paths.RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    Paths.RUN_HISTORY_FILE.touch()
    _write_dependency_milestones(Paths.MILESTONES_FILE, prereq_incomplete=False)

    # Prerequisite failed => dependent should be blocked and not runnable.
    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    state_file.write_text(
        json.dumps(
            {
                "1": {"status": "failed", "attempts": 2},
                "2": {"status": "not_started", "attempts": 0},
            },
            indent=4,
        )
    )

    result = Executor.execute_next()
    assert result["outcome"] == "blocked"

    # Ensure dependent did not run.
    state_after = json.loads(state_file.read_text())
    assert state_after["2"]["status"] == "not_started"
    assert not (Paths.SYSTEM_DIR / "results" / "milestone_2.json").exists()


def test_execute_next_integration_runs_prereq_then_dependent(tmp_path):
    Paths.refresh(tmp_path)
    Paths.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    Paths.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.REQUIREMENTS_FILE.write_text("# Requirements\n\n## Overview\n\n", encoding="utf-8")
    Paths.ARCHITECTURE_FILE.write_text("# Architecture\n\n## Design\n\n", encoding="utf-8")
    Paths.DECISIONS_FILE.write_text("# Decisions\n\n## Log\n\n", encoding="utf-8")
    Paths.RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    Paths.RUN_HISTORY_FILE.touch()
    _write_dependency_milestones(Paths.MILESTONES_FILE, prereq_incomplete=False)

    ForgeCLI.milestone_sync_state()

    res1 = Executor.execute_next()
    assert res1["milestone_id"] == 1
    assert res1["outcome"] == "complete"

    res2 = Executor.execute_next()
    assert res2["milestone_id"] == 2
    assert res2["outcome"] == "complete"

    state = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert state["2"]["status"] == "completed"


def test_execute_next_integration_skips_blocked_dependent(tmp_path):
    Paths.refresh(tmp_path)
    Paths.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    Paths.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.REQUIREMENTS_FILE.write_text("# Requirements\n\n## Overview\n\n", encoding="utf-8")
    Paths.ARCHITECTURE_FILE.write_text("# Architecture\n\n## Design\n\n", encoding="utf-8")
    Paths.DECISIONS_FILE.write_text("# Decisions\n\n## Log\n\n", encoding="utf-8")
    Paths.RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    Paths.RUN_HISTORY_FILE.touch()
    _write_dependency_milestones(Paths.MILESTONES_FILE, prereq_incomplete=True)

    ForgeCLI.milestone_sync_state()

    # First run executes milestone 1 and sets it to retry_pending (validation fails).
    res1 = Executor.execute_next()
    assert res1["milestone_id"] == 1

    # Dependent is blocked and should not be executed while prereq isn't completed.
    res2 = Executor.execute_next()
    assert res2["milestone_id"] == 1

    # After second retry, prereq should be failed; next step should be blocked (dependent still not executed).
    res3 = Executor.execute_next()
    assert res3["outcome"] == "blocked"
    assert not (Paths.SYSTEM_DIR / "results" / "milestone_2.json").exists()


def test_execute_next_resume_after_prereq_recovery(tmp_path):
    Paths.refresh(tmp_path)
    Paths.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    Paths.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.REQUIREMENTS_FILE.write_text("# Requirements\n\n## Overview\n\n", encoding="utf-8")
    Paths.ARCHITECTURE_FILE.write_text("# Architecture\n\n## Design\n\n", encoding="utf-8")
    Paths.DECISIONS_FILE.write_text("# Decisions\n\n## Log\n\n", encoding="utf-8")
    Paths.RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    Paths.RUN_HISTORY_FILE.touch()
    _write_dependency_milestones(Paths.MILESTONES_FILE, prereq_incomplete=True)

    ForgeCLI.milestone_sync_state()

    first = Executor.execute_next()
    assert first["milestone_id"] == 1
    state = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert state["1"]["status"] == "retry_pending"

    # Recover prerequisite by updating milestone 1 fields (add forge actions).
    _write_dependency_milestones(Paths.MILESTONES_FILE, prereq_incomplete=False)

    second = Executor.execute_next()
    assert second["milestone_id"] == 1
    state = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert state["1"]["status"] == "completed"

    third = Executor.execute_next()
    assert third["milestone_id"] == 2
    assert third["outcome"] == "complete"


def test_repeated_successful_executions_append_decisions(tmp_path):
    configure_project(tmp_path, _two_milestones_body())
    ForgeCLI.milestone_sync_state()
    Executor.execute_next()  # milestone 1 success
    first_content = Paths.DECISIONS_FILE.read_text(encoding="utf-8")
    assert first_content.count("Execution outcome: completed") == 1

    Executor.execute_next()  # milestone 2 success
    second_content = Paths.DECISIONS_FILE.read_text(encoding="utf-8")
    assert second_content.count("Execution outcome: completed") == 2


def test_repeated_execute_next_appends_structured_run_history(tmp_path):
    configure_project(tmp_path, _two_milestones_body())
    ForgeCLI.milestone_sync_state()
    Executor.execute_next()
    Executor.execute_next()

    lines = Paths.RUN_HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(line) for line in lines if "milestone_id" in json.loads(line)]
    assert len(entries) >= 2
    assert entries[-2]["status"] == "success"
    assert entries[-1]["status"] == "success"
