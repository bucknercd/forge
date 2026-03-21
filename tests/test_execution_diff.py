"""Diff-aware execution reporting (apply + result JSON + run history)."""

import json

from forge.executor import Executor
from forge.paths import Paths
from forge.run_history import RunHistory

from tests.forge_test_project import configure_project, forge_block


def test_executor_result_includes_outcome_and_bounded_diff(tmp_path):
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Diff test
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("DIFF_MARKER")}
""",
    )

    Executor.execute_milestone(1)

    result = json.loads((Paths.SYSTEM_DIR / "results" / "milestone_1.json").read_text())
    assert "artifact_summary" in result
    assert "changed" in result["artifact_summary"]
    assert result["actions_applied"]

    append = next(
        a for a in result["actions_applied"] if a["type"] == "append_section"
    )
    assert append["outcome"] == "changed"
    assert append["path"].endswith("docs/requirements.md")
    assert append["diff"]
    assert "diff_truncated" in append

    mark = next(
        a for a in result["actions_applied"] if a["type"] == "mark_milestone_completed"
    )
    assert mark["outcome"] in ("changed", "skipped")


def test_idempotent_append_records_skipped_outcome(tmp_path):
    marker = "IDEM_ONCE"
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Idempotent
- **Objective**: O
- **Scope**: S
- **Validation**: V
- **Forge Actions**:
  - append_section requirements Overview | {marker}
  - append_section requirements Overview | {marker}
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements {marker}
""",
    )

    Executor.execute_milestone(1)
    result = json.loads((Paths.SYSTEM_DIR / "results" / "milestone_1.json").read_text())
    appends = [a for a in result["actions_applied"] if a["type"] == "append_section"]
    assert len(appends) == 2
    outcomes = [a["outcome"] for a in appends]
    assert outcomes.count("changed") == 1
    assert outcomes.count("skipped") == 1
    skipped = [a for a in appends if a["outcome"] == "skipped"][0]
    assert skipped.get("diff") is None


def test_run_history_milestone_attempt_includes_artifact_summary(tmp_path):
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.RUN_HISTORY_FILE = Paths.SYSTEM_DIR / "run_history.log"
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)

    RunHistory.log_milestone_attempt(
        milestone_id=1,
        milestone_title="M1",
        status="success",
        artifact_summary="1 changed, 0 skipped; artifacts: docs/a.md",
    )
    entry = json.loads(Paths.RUN_HISTORY_FILE.read_text(encoding="utf-8").strip())
    assert entry["artifact_summary"] == "1 changed, 0 skipped; artifacts: docs/a.md"


def test_unified_diff_helper_returns_empty_when_identical():
    from forge.execution.text_diff import unified_diff_bounded

    text, trunc = unified_diff_bounded("same", "same", "x.txt")
    assert text == ""
    assert trunc is False
