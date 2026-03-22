"""
write_file end-to-end payload integrity (parse → plan → apply → disk == canonical body).

Does not use LLM planner; exercises ExecutionPlan.from_serializable and parse_forge_action_line.
"""

from __future__ import annotations

import json

import pytest

from forge.design_manager import Milestone
from forge.execution.models import (
    ActionMarkMilestoneCompleted,
    ActionWriteFile,
    ExecutionPlan,
)
from forge.execution.parse import parse_forge_action_line
from forge.execution.plan import ExecutionPlanBuilder
from forge.execution.write_file_integrity import (
    WriteFileIntegrityError,
    sha256_utf8,
    verify_write_file_disk_matches,
)
from forge.paths import Paths
from forge.execution.apply import ArtifactActionApplier


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "")


REALISTIC_PY = '''\
import sys

def parse_log(file_path):
    if not file_path:
        raise ValueError("missing path")
    error_message = "ok"
    with open(file_path) as f:
        for line in f:
            if "ERR" in line:
                print(f"{line!r}: {error_message!s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(parse_log(sys.argv[1]) if len(sys.argv) != 1 else 0)
'''


def test_parse_apply_disk_exact_match_realistic_body(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    raw = f"write_file src/parse_log.py | {_esc(REALISTIC_PY)}"
    m = Milestone(1, "t", "o", "s", "v", forge_actions=[raw, "mark_milestone_completed"])
    plan = ExecutionPlanBuilder.build(m)
    wf = next(a for a in plan.actions if isinstance(a, ActionWriteFile))
    assert wf.body == REALISTIC_PY
    ArtifactActionApplier(Paths).apply(plan, m, dry_run=False)
    disk = (Paths.BASE_DIR / "src" / "parse_log.py").read_text(encoding="utf-8")
    assert disk == REALISTIC_PY
    assert sha256_utf8(disk) == sha256_utf8(REALISTIC_PY)


def test_round_trip_json_plan_matches_disk(tmp_path, monkeypatch):
    """Simulate reviewed plan JSON → from_serializable → apply (vertical-slice apply path)."""
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    plan = ExecutionPlan(
        milestone_id=1,
        actions=[
            ActionWriteFile(rel_path="src/t.py", body=REALISTIC_PY),
            ActionMarkMilestoneCompleted(),
        ],
    )
    ser = plan.to_serializable()
    roundtrip = ExecutionPlan.from_serializable(ser)
    m = Milestone(1, "t", "o", "s", "v")
    ArtifactActionApplier(Paths).apply(roundtrip, m, dry_run=False)
    disk = (Paths.BASE_DIR / "src" / "t.py").read_text(encoding="utf-8")
    assert disk == REALISTIC_PY


def test_fstrings_quotes_colons_parentheses_preserved():
    body = '''\
x = {"a": 1, "b": (2, 3)}
y = f"hello {x['a']!r}"
z = (lambda: None)()
'''
    raw = f"write_file src/x.py | {_esc(body)}"
    m = Milestone(1, "t", "o", "s", "v")
    act = parse_forge_action_line(raw, m)
    assert isinstance(act, ActionWriteFile)
    assert act.body == body


def test_verify_write_file_disk_matches_raises_on_mismatch(tmp_path):
    p = tmp_path / "f.py"
    expected = "canonical full content\n"
    p.write_text("wrong", encoding="utf-8")
    with pytest.raises(WriteFileIntegrityError) as exc:
        verify_write_file_disk_matches(p, expected, rel_path="f.py")
    assert "integrity failure" in str(exc.value).lower()
    assert exc.value.expected_len == len(expected)
    assert exc.value.got_len == len("wrong")


def test_json_plan_load_preserves_body_unicode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    body = "café\nτ\n\U0001f680\n"
    plan = ExecutionPlan(
        milestone_id=1,
        actions=[ActionWriteFile(rel_path="src/u.py", body=body)],
    )
    ser = plan.to_serializable()
    dumped = json.dumps(ser, ensure_ascii=False)
    loaded = json.loads(dumped)
    rt = ExecutionPlan.from_serializable(loaded)
    wf = rt.actions[0]
    assert isinstance(wf, ActionWriteFile)
    assert wf.body == body
    m = Milestone(1, "t", "o", "s", "v")
    ArtifactActionApplier(Paths).apply(rt, m, dry_run=False)
    assert (Paths.BASE_DIR / "src" / "u.py").read_text(encoding="utf-8") == body