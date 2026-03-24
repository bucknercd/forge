"""Regression: LLM-escaped quotes in write_file bodies + profile-aware src/__init__.py."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from forge.design_manager import Milestone
from forge.execution.apply import ArtifactActionApplier
from forge.execution.models import ActionWriteFile, ExecutionPlan
from forge.execution.write_body_sanitize import (
    sanitize_write_file_body,
    should_ensure_src_init_py,
)
from forge.paths import Paths

_CORRUPT_GO = '''package main

import \\"fmt\\"
import \\"net/http\\"

func main() {
	http.HandleFunc(\\"/\\", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, \\"ok\\")
	})
}
'''

_EXPECTED_GO = '''package main

import "fmt"
import "net/http"

func main() {
	http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		fmt.Fprint(w, "ok")
	})
}
'''


def test_sanitize_go_strips_spurious_slash_quotes_outside_strings() -> None:
    out, meta = sanitize_write_file_body(
        _CORRUPT_GO,
        normalized_rel_path="src/server.go",
        project_profile="go",
    )
    assert out == _EXPECTED_GO
    assert meta.get("slash_quote_unescape") == "c_like_scanner"


def test_sanitize_go_preserves_escaped_quote_inside_string_literal() -> None:
    body = 'package p\n\nvar s = "hello \\"world\\""\n'
    out, _meta = sanitize_write_file_body(
        body,
        normalized_rel_path="x.go",
        project_profile="go",
    )
    assert out == body


def test_sanitize_python_preserves_escaped_quote_inside_string() -> None:
    body = 'x = "hello \\"world\\""\n'
    out, _ = sanitize_write_file_body(
        body,
        normalized_rel_path="src/m.py",
        project_profile="python",
    )
    assert out == body


def test_should_ensure_src_init_py_go_vs_python() -> None:
    assert not should_ensure_src_init_py(
        normalized_rel_path="src/server.go", project_profile="go"
    )
    assert should_ensure_src_init_py(
        normalized_rel_path="src/m.py", project_profile="python"
    )
    assert not should_ensure_src_init_py(
        normalized_rel_path="src/server.go", project_profile=None
    )
    assert should_ensure_src_init_py(
        normalized_rel_path="src/m.py", project_profile=None
    )


def test_apply_go_under_src_no_init_py(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    m = Milestone(1, "t", "o", "s", "v")
    plan = ExecutionPlan(
        milestone_id=1,
        actions=[ActionWriteFile(rel_path="src/server.go", body=_CORRUPT_GO)],
    )
    ArtifactActionApplier(Paths).apply(plan, m, dry_run=False, project_profile="go")
    disk = (Paths.BASE_DIR / "src" / "server.go").read_text(encoding="utf-8")
    assert "\\\"" not in disk
    assert 'import "fmt"' in disk
    assert 'import "net/http"' in disk
    assert not (Paths.BASE_DIR / "src" / "__init__.py").exists()


def test_apply_python_src_creates_init_py(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    m = Milestone(1, "t", "o", "s", "v")
    body = "def f():\n    return 1\n"
    plan = ExecutionPlan(
        milestone_id=1,
        actions=[ActionWriteFile(rel_path="src/mod.py", body=body)],
    )
    ArtifactActionApplier(Paths).apply(plan, m, dry_run=False, project_profile="python")
    assert (Paths.BASE_DIR / "src" / "mod.py").read_text(encoding="utf-8") == body
    assert (Paths.BASE_DIR / "src" / "__init__.py").exists()


def test_profile_switch_go_then_python_isolation(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    m = Milestone(1, "t", "o", "s", "v")
    go_plan = ExecutionPlan(
        milestone_id=1,
        actions=[ActionWriteFile(rel_path="src/server.go", body=_CORRUPT_GO)],
    )
    ArtifactActionApplier(Paths).apply(go_plan, m, dry_run=False, project_profile="go")
    assert not (Paths.BASE_DIR / "src" / "__init__.py").exists()

    py_plan = ExecutionPlan(
        milestone_id=1,
        actions=[ActionWriteFile(rel_path="src/mod.py", body="x = 1\n")],
    )
    ArtifactActionApplier(Paths).apply(py_plan, m, dry_run=False, project_profile="python")
    assert (Paths.BASE_DIR / "src" / "__init__.py").exists()
    go_disk = (Paths.BASE_DIR / "src" / "server.go").read_text(encoding="utf-8")
    assert 'import "fmt"' in go_disk


@pytest.mark.skipif(not shutil.which("go"), reason="go toolchain not installed")
def test_go_run_server_sanitized(tmp_path, monkeypatch) -> None:
    import subprocess

    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    m = Milestone(1, "t", "o", "s", "v")
    plan = ExecutionPlan(
        milestone_id=1,
        actions=[ActionWriteFile(rel_path="src/server.go", body=_CORRUPT_GO)],
    )
    ArtifactActionApplier(Paths).apply(plan, m, dry_run=False, project_profile="go")
    proc = subprocess.run(
        ["go", "run", str(Path("src") / "server.go")],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, (proc.stdout, proc.stderr)
