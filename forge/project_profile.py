"""
Lightweight project/language profile detection and guidance.

This module intentionally stays small and deterministic. It provides a thin
internal abstraction to guide planner/repair behavior without redesigning the
execution engine.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class ProjectProfile:
    profile_name: str  # python | go | terraform | unknown
    source_conventions: list[str]
    test_conventions: list[str]
    package_or_module_conventions: list[str]
    test_command_hint: str
    validation_hint: str
    stub_signals: list[str]
    planner_guidance: str
    repair_guidance: str


_PROFILES: dict[str, ProjectProfile] = {
    "python": ProjectProfile(
        profile_name="python",
        source_conventions=[
            "prefer src/ for implementation modules",
            "prefer tests/ for pytest test modules",
        ],
        test_conventions=[
            "pytest test files under tests/",
            "run from repo root with pytest -q",
        ],
        package_or_module_conventions=[
            "avoid relative imports like from ..src",
            "prefer repo-root-import-safe module references",
        ],
        test_command_hint="pytest -q",
        validation_hint="path_file_contains for src/ and tests/ behavior assertions",
        stub_signals=["only_cli_scaffold", "no_processing_logic", "only_main_wrapper"],
        planner_guidance=(
            "Python profile: keep imports compatible with pytest from repo root; "
            "avoid relative imports such as from ..src. For new tests, prefer "
            "write_file tests/<name>.py with complete test content."
        ),
        repair_guidance=(
            "Python repair: converge on one import/layout strategy; do not oscillate "
            "between relative and package imports."
        ),
    ),
    "go": ProjectProfile(
        profile_name="go",
        source_conventions=[
            "prefer .go source files with package declarations",
            "prefer *_test.go test files",
        ],
        test_conventions=[
            "go test ./...",
            "tests should compile with package conventions",
        ],
        package_or_module_conventions=[
            "use valid package names and imports",
            "avoid Python-style import/layout assumptions",
        ],
        test_command_hint="go test ./...",
        validation_hint="path_file_contains for package/function/test names",
        stub_signals=["go_todo_stub", "go_unimplemented_logic"],
        planner_guidance=(
            "Go profile: always include write_file go.mod at repo root (module line + go "
            "version) before or with any *.go files so `go test ./...` works. If you add "
            "*_test.go, also add non-test .go files that implement the behavior under test "
            "(do not ship tests alone). For HTTP handlers, prefer testing a concrete "
            "http.Handler with httptest.NewRecorder, or register routes with http.HandleFunc "
            "before calling http.DefaultServeMux.ServeHTTP; avoid tests that hit the default "
            "mux with no registration. Avoid Python-style paths (no src/__init__.py)."
        ),
        repair_guidance=(
            "Go repair: add or fix go.mod at repo root; ensure every *_test.go has matching "
            "implementation .go files; register HTTP handlers if tests use "
            "http.DefaultServeMux, or rewrite tests to use httptest against an explicit "
            "handler. Keep packages compile-testable with go test ./..."
        ),
    ),
    "terraform": ProjectProfile(
        profile_name="terraform",
        source_conventions=[
            "prefer main.tf plus related .tf files",
            "keep provider/resource/variable/output blocks explicit",
        ],
        test_conventions=[
            "terraform validate from repo root or module root",
        ],
        package_or_module_conventions=[
            "HCL blocks, not code-language imports",
        ],
        test_command_hint="terraform validate",
        validation_hint="path_file_contains for resource/variable/output semantics",
        stub_signals=["tf_placeholder_only", "no_meaningful_terraform_blocks"],
        planner_guidance=(
            "Terraform profile: produce canonical .tf layout and validate-friendly "
            "resource/variable/output blocks; avoid code/test assumptions from Python/Go."
        ),
        repair_guidance=(
            "Terraform repair: replace placeholder-only HCL with meaningful blocks "
            "required by task behavior."
        ),
    ),
    "unknown": ProjectProfile(
        profile_name="unknown",
        source_conventions=["use conservative repo-root-safe file conventions"],
        test_conventions=["prefer explicit test files/commands in plan"],
        package_or_module_conventions=["avoid language-specific assumptions"],
        test_command_hint="",
        validation_hint="prefer path_file_contains/file_contains for explicit behavior checks",
        stub_signals=["no_processing_logic"],
        planner_guidance=(
            "Unknown profile: choose conservative, explicit file edits and avoid "
            "language-specific assumptions."
        ),
        repair_guidance=(
            "Unknown repair: keep fixes minimal and align strictly with task validations."
        ),
    ),
}


def _token_blob(texts: list[str] | None) -> str:
    return "\n".join((texts or [])).lower()


def detect_project_profile(
    *,
    texts: list[str] | None = None,
    file_paths: list[str] | None = None,
) -> ProjectProfile:
    blob = _token_blob(texts)
    paths = [p.replace("\\", "/").lower() for p in (file_paths or [])]

    py_score = 0
    go_score = 0
    tf_score = 0

    if any(p.endswith(".py") for p in paths):
        py_score += 3
    if any(p.endswith(".go") for p in paths):
        go_score += 3
    if any(p.endswith(".tf") for p in paths):
        tf_score += 3

    if re.search(r"\bpython\b|\bpytest\b|\.py\b|python cli", blob):
        py_score += 3
    if re.search(r"\bgo\b|\bgolang\b|go test|\.go\b", blob):
        go_score += 3
    if re.search(r"\bterraform\b|\.tf\b|terraform validate|hcl\b", blob):
        tf_score += 3

    # Path-shape hints
    if any("/tests/" in p or p.startswith("tests/") for p in paths) and (
        "pytest" in blob or any(p.endswith(".py") for p in paths)
    ):
        py_score += 1

    best = max((py_score, "python"), (go_score, "go"), (tf_score, "terraform"))
    if best[0] <= 0:
        return _PROFILES["unknown"]
    return _PROFILES[best[1]]


def project_profile_for_task_ir(task_ir: Any) -> ProjectProfile:
    texts: list[str] = [
        str(getattr(task_ir, "summary", "") or ""),
        str(getattr(task_ir, "objective", "") or ""),
    ]
    texts.extend([str(x) for x in (getattr(task_ir, "requirements", []) or [])])
    texts.extend([str(x) for x in (getattr(task_ir, "validations", []) or [])])

    file_paths: list[str] = []
    for line in (getattr(task_ir, "embedded_actions", []) or []):
        s = str(line)
        m = re.match(r"^\s*(?:write_file|insert_after_in_file|insert_before_in_file|replace_text_in_file|replace_block_in_file|replace_lines_in_file)\s+(\S+)", s)
        if m:
            file_paths.append(m.group(1))
    return detect_project_profile(texts=texts, file_paths=file_paths)


def planner_guidance_for_profile(profile: ProjectProfile) -> str:
    return profile.planner_guidance


def repair_guidance_for_profile(profile: ProjectProfile) -> str:
    return profile.repair_guidance


def stub_signals_for_profile(profile_name: str) -> list[str]:
    return list(_PROFILES.get(profile_name, _PROFILES["unknown"]).stub_signals)


def get_project_profile(profile_name: str) -> ProjectProfile:
    return _PROFILES.get(profile_name, _PROFILES["unknown"])

