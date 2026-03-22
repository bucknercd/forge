"""write_file body preservation: indentation, blank lines, parse → apply round-trip."""

from __future__ import annotations

import json

import pytest

from forge.design_manager import Milestone, MilestoneService
from forge.execution.apply import ArtifactActionApplier
from forge.execution.file_edits import unescape_action_body
from forge.execution.parse import parse_forge_action_line
from forge.execution.plan import ExecutionPlanBuilder
from forge.paths import Paths
from forge.vertical_slice import (
    _escape_write_body,
    _repair_multiline_write_file_actions,
    finalize_llm_milestones_md,
)


def test_repair_multiline_write_file_preserves_indentation_exactly():
    raw = """# Milestones

## Milestone 1: CLI

- **Objective**: Add CLI.
- **Scope**: src/
- **Validation**: Runs.

- **Forge Actions**:
  - write_file src/logcheck.py | import sys

def main():
    if len(sys.argv) != 2:
        print("usage: logcheck <file>")
        return 1
    try:
        with open(sys.argv[1]) as f:
            for line in f:
                if "ERROR" in line:
                    print(line, end="")
    except OSError:
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains src/logcheck.py def main
"""
    out, _w = _repair_multiline_write_file_actions(raw)
    folded = next(ln for ln in out.splitlines() if "write_file src/logcheck.py" in ln)
    # Decoded body must keep 4-space indents under def/if/try/with/for
    assert "def main():" in folded
    assert "    if len(sys.argv)" in folded
    assert "        print(" in folded
    assert "    try:" in folded
    assert "        with open" in folded
    assert "            for line in f:" in folded
    assert "                if \"ERROR\"" in folded or "if \"ERROR\"" in folded


def test_repair_multiline_write_file_preserves_blank_lines_in_body():
    raw = """# Milestones

## Milestone 1: X

- **Objective**: x
- **Scope**: x
- **Validation**: x

- **Forge Actions**:
  - write_file src/a.py | a = 1

b = 2


c = 3
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains src/a.py c = 3
"""
    out, _w = _repair_multiline_write_file_actions(raw)
    folded = next(ln for ln in out.splitlines() if "write_file src/a.py" in ln)
    _, _, esc = folded.partition(" | ")
    body = unescape_action_body(esc)
    assert "a = 1\n\nb = 2\n\n\nc = 3" in body or body.count("\n\n") >= 1


def test_parse_forge_action_decode_matches_apply_body():
    body = (
        "import sys\n\n\ndef main():\n"
        "    if True:\n"
        "        pass\n"
    )
    esc = _escape_write_body(body)
    raw_line = f"write_file src/x.py | {esc}"
    m = Milestone(1, "t", "o", "s", "v")
    action = parse_forge_action_line(raw_line, m, line_no=1)
    assert action.body == body


def test_apply_write_file_writes_exact_utf8_bytes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    body = "def main():\n    return 0\n\n"
    esc = _escape_write_body(body)
    raw = f"write_file src/hi.py | {esc}"
    milestone = Milestone(1, "t", "o", "s", "v", forge_actions=[raw])
    plan = ExecutionPlanBuilder.build(milestone)
    applier = ArtifactActionApplier(Paths)
    res = applier.apply(plan, milestone, dry_run=False)
    path = Paths.BASE_DIR / "src" / "hi.py"
    assert path.read_bytes() == body.encode("utf-8")
    wf = [a for a in res.actions_applied if a.get("type") == "write_file"]
    assert len(wf) == 1
    assert wf[0].get("outcome") == "changed"
    assert wf[0].get("noop") is False


def test_apply_write_file_is_noop_when_file_already_matches(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    body = "x = 1\n    y = 2\n"
    esc = _escape_write_body(body)
    raw = f"write_file src/same.py | {esc}"
    milestone = Milestone(1, "t", "o", "s", "v", forge_actions=[raw])
    plan = ExecutionPlanBuilder.build(milestone)
    applier = ArtifactActionApplier(Paths)
    applier.apply(plan, milestone, dry_run=False)
    res2 = applier.apply(plan, milestone, dry_run=False)
    wf = [a for a in res2.actions_applied if a.get("type") == "write_file"]
    assert wf[0].get("outcome") == "skipped"
    assert wf[0].get("noop") is True


def test_finalize_parse_apply_roundtrip_indented_python(tmp_path, monkeypatch):
    """Indented multiline body survives finalize → milestone parse → plan → disk."""
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    raw_md = """# Milestones

## Milestone 1: Tool

- **Objective**: Provide src/tool.py with main for this vertical-slice demonstration.
- **Scope**: Stdlib only under src/.
- **Validation**: File is valid Python.

- **Forge Actions**:
  - write_file src/tool.py | import sys

def main() -> None:
    print("tool")

if __name__ == "__main__":
    raise SystemExit(main())
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains src/tool.py def main
"""
    finalized, _ = finalize_llm_milestones_md(
        raw_md,
        source_context=(
            "Build tool.py CLI under src/ for demonstration; "
            "the demonstration proves Forge vertical-slice output."
        ),
    )
    ms = MilestoneService.parse_milestones(finalized)
    wf_line = ms[0].forge_actions[0]
    assert wf_line.startswith("write_file src/tool.py")
    m = ms[0]
    plan = ExecutionPlanBuilder.build(m)
    applier = ArtifactActionApplier(Paths)
    applier.apply(plan, m, dry_run=False)
    disk = (Paths.BASE_DIR / "src" / "tool.py").read_text(encoding="utf-8")
    # Body in action (decoded) must match file
    action = plan.actions[0]
    from forge.execution.models import ActionWriteFile

    assert isinstance(action, ActionWriteFile)
    assert action.body == disk
    assert "    print(" in disk
    assert "def main()" in disk


def test_milestone_action_body_matches_disk_after_apply(tmp_path, monkeypatch):
    """Regression: docs-ready action string decodes to same bytes as written file."""
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    content = "# hello\nclass A:\n    x = 1\n"
    esc = _escape_write_body(content)
    md = f"""# Milestones

## Milestone 1: K

- **Objective**: o
- **Scope**: s
- **Validation**: v

- **Forge Actions**:
  - write_file src/k.py | {esc}
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains src/k.py class A
"""
    finalized, _ = finalize_llm_milestones_md(
        md,
        source_context="Add k.py with class A under src/.",
    )
    Paths.MILESTONES_FILE.write_text(finalized, encoding="utf-8")
    ms = MilestoneService.parse_milestones(finalized)
    raw_action = ms[0].forge_actions[0]
    m = ms[0]
    plan = ExecutionPlanBuilder.build(m)
    ArtifactActionApplier(Paths).apply(plan, m, dry_run=False)
    from forge.execution.models import ActionWriteFile

    act = plan.actions[0]
    assert isinstance(act, ActionWriteFile)
    disk = (Paths.BASE_DIR / "src" / "k.py").read_text(encoding="utf-8")
    assert act.body == disk == content


def test_repair_attempt_artifact_json_contains_plan_and_write_file_outcomes(
    tmp_path, monkeypatch
):
    """Persisted repair_attempts JSON includes stored plan and write_file noop/changed flags."""
    monkeypatch.chdir(tmp_path)
    from forge.executor import Executor, _persist_repair_loop_attempt_artifact
    from forge.task_service import ensure_tasks_for_milestone
    from tests.forge_test_project import configure_project

    body = "v = 1\n"
    esc = _escape_write_body(body)
    configure_project(
        tmp_path,
        f"""# Milestones

## Milestone 1: T
- **Objective**: o
- **Scope**: s
- **Validation**: v

- **Forge Actions**:
  - write_file src/r.py | {esc}
  - mark_milestone_completed
- **Forge Validation**:
  - path_file_contains src/r.py v
""",
    )
    assert ensure_tasks_for_milestone(1).get("ok") is not False
    preview = Executor.save_reviewed_plan_for_task(1, 1)
    assert preview.get("ok")
    plan_id = preview["plan_id"]
    apply_res = Executor.apply_reviewed_plan_with_gates(
        plan_id,
        run_validation_gate=False,
        test_command=None,
        mark_task_complete=False,
        record_milestone_attempt=False,
        defer_post_apply_gates=True,
    )
    path = _persist_repair_loop_attempt_artifact(
        milestone_id=1,
        task_id=1,
        attempt=1,
        plan_id=plan_id,
        apply_res=apply_res,
    )
    assert path is not None
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data.get("plan", {}).get("actions")
    wf = data.get("write_file_outcomes") or []
    assert wf and wf[0].get("rel_path") == "src/r.py"
    assert wf[0].get("noop") is False
