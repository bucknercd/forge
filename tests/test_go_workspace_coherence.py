"""Go workspace coherence checks (go.mod, impl vs tests, DefaultServeMux wiring)."""

from __future__ import annotations

from forge.design_manager import Milestone
from forge.execution.apply import ArtifactActionApplier
from forge.execution.models import ActionWriteFile, ExecutionPlan
from forge.execution.safe_paths import resolve_safe_project_path
from forge.go_workspace_coherence import check_go_workspace_coherence
from forge.executor import Executor
from forge.paths import Paths
from forge.validator import Validator
from tests.forge_test_project import configure_project, forge_block


def test_check_go_passes_when_no_go_files(tmp_path) -> None:
    assert check_go_workspace_coherence(tmp_path) == (True, "")


def test_check_go_fails_without_go_mod(tmp_path) -> None:
    d = tmp_path / "tests"
    d.mkdir(parents=True)
    (d / "a.go").write_text("package main\n", encoding="utf-8")
    ok, reason = check_go_workspace_coherence(tmp_path)
    assert ok is False
    assert "no go.mod" in reason.lower()
    assert "go workspace coherence" in reason.lower()


def test_check_go_fails_tests_only(tmp_path) -> None:
    (tmp_path / "go.mod").write_text("module x\ngo 1.22\n", encoding="utf-8")
    d = tmp_path / "tests"
    d.mkdir(parents=True)
    (d / "a_test.go").write_text("package main\n", encoding="utf-8")
    ok, reason = check_go_workspace_coherence(tmp_path)
    assert ok is False
    assert "only *_test.go" in reason.lower() or "*_test.go" in reason


def test_check_go_passes_with_impl_and_tests(tmp_path) -> None:
    (tmp_path / "go.mod").write_text("module x\ngo 1.22\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.go").write_text("package main\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "a_test.go").write_text("package main\n", encoding="utf-8")
    assert check_go_workspace_coherence(tmp_path) == (True, "")


def test_check_go_fails_default_serve_mux_without_handlefunc(tmp_path) -> None:
    (tmp_path / "go.mod").write_text("module x\ngo 1.22\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.go").write_text(
        "package main\nfunc main() {}\n", encoding="utf-8"
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "main_test.go").write_text(
        """package main
import (
  "net/http"
  "net/http/httptest"
  "testing"
)
func TestX(t *testing.T) {
  req := httptest.NewRequest(http.MethodGet, "/", nil)
  rr := httptest.NewRecorder()
  http.DefaultServeMux.ServeHTTP(rr, req)
}
""",
        encoding="utf-8",
    )
    ok, reason = check_go_workspace_coherence(tmp_path)
    assert ok is False
    assert "DefaultServeMux" in reason
    assert "HandleFunc" in reason or "http.Handle" in reason


def test_check_go_passes_default_serve_mux_when_handlefunc_present(tmp_path) -> None:
    (tmp_path / "go.mod").write_text("module x\ngo 1.22\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.go").write_text(
        """package main
import "net/http"
func init() { http.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {}) }
func main() {}
""",
        encoding="utf-8",
    )
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "main_test.go").write_text(
        """package main
import (
  "net/http"
  "net/http/httptest"
  "testing"
)
func TestX(t *testing.T) {
  req := httptest.NewRequest(http.MethodGet, "/", nil)
  rr := httptest.NewRecorder()
  http.DefaultServeMux.ServeHTTP(rr, req)
}
""",
        encoding="utf-8",
    )
    assert check_go_workspace_coherence(tmp_path) == (True, "")


def test_resolve_safe_project_path_allows_go_mod_at_root(tmp_path) -> None:
    p = resolve_safe_project_path("go.mod", tmp_path)
    assert p == tmp_path / "go.mod"


def test_validator_runs_go_coherence_after_rules(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    configure_project(
        tmp_path,
        f"""
# Milestones

## Milestone 1: Go slice
- **Objective**: O
- **Scope**: S
- **Validation**: V
{forge_block("GOVAL")}
""",
    )
    Executor.execute_milestone(1)
    assert Validator.validate_milestone_with_report(1)[0] is True

    (tmp_path / "go.mod").write_text("module x\ngo 1.22\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "api_test.go").write_text(
        "package main\nfunc TestA(t *testing.T) {}\n", encoding="utf-8"
    )

    ok, reason = Validator.validate_milestone_with_report(1)
    assert ok is False
    assert "Go workspace coherence" in reason
    assert "implementation" in reason.lower()


def test_apply_can_write_go_mod_at_root(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    Paths.refresh(tmp_path)
    Paths.ensure_project_structure()
    body = "module example.com/demo\n\ngo 1.22\n"
    plan = ExecutionPlan(
        milestone_id=1,
        actions=[ActionWriteFile(rel_path="go.mod", body=body)],
    )
    m = Milestone(1, "t", "o", "s", "v")
    res = ArtifactActionApplier(Paths).apply(plan, m, dry_run=False)
    assert not res.errors
    assert (Paths.BASE_DIR / "go.mod").read_text(encoding="utf-8") == body
