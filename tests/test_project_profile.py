from __future__ import annotations

from forge.project_profile import (
    detect_project_profile,
    planner_guidance_for_profile,
    project_profile_for_task_ir,
    repair_guidance_for_profile,
)
from forge.task_ir import compile_task_to_ir
from forge.task_service import Task


def _task(
    *,
    objective: str,
    summary: str = "",
    validation: str = "",
    forge_actions: list[str] | None = None,
) -> Task:
    return Task(
        id=1,
        milestone_id=1,
        title="t",
        objective=objective,
        summary=summary,
        depends_on=[],
        files_allowed=None,
        validation=validation,
        done_when="done",
        status="not_started",
        forge_actions=list(forge_actions or []),
        forge_validation=[],
    )


def test_detect_project_profile_python():
    p = detect_project_profile(
        texts=["Python CLI with pytest", "src/app.py"],
        file_paths=["src/app.py", "tests/test_app.py"],
    )
    assert p.profile_name == "python"


def test_detect_project_profile_go():
    p = detect_project_profile(
        texts=["Build golang service and run go test ./..."],
        file_paths=["cmd/main.go", "pkg/x_test.go"],
    )
    assert p.profile_name == "go"


def test_detect_project_profile_terraform():
    p = detect_project_profile(
        texts=["terraform module and terraform validate"],
        file_paths=["main.tf", "variables.tf"],
    )
    assert p.profile_name == "terraform"


def test_detect_project_profile_unknown():
    p = detect_project_profile(texts=["generic project"], file_paths=["README.md"])
    assert p.profile_name == "unknown"


def test_project_profile_for_task_ir_python():
    task_ir = compile_task_to_ir(
        _task(
            objective="Implement Python CLI parser and pytest tests",
            summary="count ERROR lines",
            validation="pytest -q",
            forge_actions=["write_file src/logcheck.py | def main():\\n    return 0\\n"],
        )
    )
    p = project_profile_for_task_ir(task_ir)
    assert p.profile_name == "python"


def test_guidance_differs_by_profile():
    py = detect_project_profile(texts=["python pytest"], file_paths=["src/a.py"])
    go = detect_project_profile(texts=["golang go test"], file_paths=["main.go"])
    tf = detect_project_profile(texts=["terraform validate"], file_paths=["main.tf"])

    py_g = planner_guidance_for_profile(py)
    go_g = planner_guidance_for_profile(go)
    tf_g = planner_guidance_for_profile(tf)

    assert "pytest" in py_g.lower() or "python" in py_g.lower()
    assert "go test" in go_g.lower() or "go profile" in go_g.lower()
    assert "terraform" in tf_g.lower()
    assert "from ..src" in py_g
    assert "from ..src" not in go_g
    assert "from ..src" not in tf_g


def test_repair_guidance_not_python_polluted_for_non_python():
    go = detect_project_profile(texts=["go test ./..."], file_paths=["service.go"])
    tf = detect_project_profile(texts=["terraform"], file_paths=["main.tf"])
    assert "pytest" not in repair_guidance_for_profile(go).lower()
    assert "pytest" not in repair_guidance_for_profile(tf).lower()

