from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from forge.paths import Paths


_GENERATED_CODE_ROOTS = ("src", "tests", "examples", "artifacts")


def _is_within_allowed_generated_roots(p: Path) -> bool:
    try:
        rel = p.resolve().relative_to(Paths.BASE_DIR.resolve()).as_posix()
    except Exception:
        return False
    return rel.startswith(tuple(r + "/" for r in _GENERATED_CODE_ROOTS))


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists() and (path.is_file() or path.is_symlink()):
            path.unlink()
    except Exception:
        # Best-effort cleanup; do not hard-fail a user workflow.
        return


def _safe_rmtree(path: Path) -> None:
    try:
        if path.exists() and path.is_dir():
            shutil.rmtree(path)
    except Exception:
        return


def _collect_written_files_from_json(path: Path) -> set[Path]:
    """
    Collect file paths written by forge from stored artifacts.

    We parse the reviewed plans and milestone/result JSON so we can delete only
    previously-written targets, rather than wiping user code blindly.
    """
    out: set[Path] = set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return out

    # reviewed_plan payload: { targets: [{path: "..."}] }
    if isinstance(payload, dict):
        targets = payload.get("targets")
        if isinstance(targets, list):
            for t in targets:
                if isinstance(t, dict) and "path" in t:
                    p = Path(str(t["path"]))
                    if _is_within_allowed_generated_roots(p):
                        out.add(p)

        # milestone result payload: { actions_applied: [{type, path, ...}, ...] }
        ap = payload.get("actions_applied")
        if isinstance(ap, list):
            for a in ap:
                if not isinstance(a, dict):
                    continue
                if a.get("type") != "write_file":
                    continue
                rel = a.get("path")
                if not rel:
                    continue
                p = Paths.BASE_DIR / str(rel)
                if _is_within_allowed_generated_roots(p):
                    out.add(p)

        # repair_attempt summary payloads sometimes contain write_file_outcomes
        outcomes = payload.get("write_file_outcomes")
        if isinstance(outcomes, list):
            for o in outcomes:
                if not isinstance(o, dict):
                    continue
                rel = o.get("path")
                if not rel:
                    continue
                p = Paths.BASE_DIR / str(rel)
                if _is_within_allowed_generated_roots(p):
                    out.add(p)

    return out


def collect_generated_files_for_reset() -> set[Path]:
    """
    Best-effort set of files that forge previously wrote in this repo.
    """
    out: set[Path] = set()

    reviewed = Paths.SYSTEM_DIR / "reviewed_plans"
    if reviewed.exists():
        for p in reviewed.glob("*.json"):
            out |= _collect_written_files_from_json(p)

    results = Paths.SYSTEM_DIR / "results"
    if results.exists():
        for p in results.rglob("*.json"):
            out |= _collect_written_files_from_json(p)

    # Auto-created: we create `src/__init__.py` when writing src/*.py. That file
    # is not part of write_file actions, so it won't appear in targets.
    init_py = Paths.BASE_DIR / "src" / "__init__.py"
    if init_py.exists():
        if _is_within_allowed_generated_roots(init_py):
            out.add(init_py)

    return out


def reset_generated_only() -> dict[str, Any]:
    """
    Fresh-start reset intended for switching apps/ideas in the same directory.

    - Clears execution state: tasks, reviewed plans, results, milestone_state.
    - Clears stored artifacts: .forge/runs, .artifacts.
    - Deletes previously-written generated code (src/tests/examples/artifacts)
      using recorded reviewed plans/results; also removes `src/__init__.py` and
      `tests/forge_generated/` as additional cleanup.
    """
    generated_files = collect_generated_files_for_reset()

    wiped: dict[str, Any] = {
        "wiped_generated_files": sorted(str(p) for p in generated_files),
        "tasks_removed": False,
        "reviewed_plans_removed": False,
        "results_removed": False,
        "milestone_state_removed": False,
        "runs_removed": False,
        "artifacts_removed": False,
        "forge_generated_tests_removed": False,
    }

    _safe_rmtree(Paths.SYSTEM_DIR / "tasks")
    wiped["tasks_removed"] = True
    _safe_rmtree(Paths.SYSTEM_DIR / "reviewed_plans")
    wiped["reviewed_plans_removed"] = True
    _safe_rmtree(Paths.SYSTEM_DIR / "results")
    wiped["results_removed"] = True
    _safe_unlink(Paths.SYSTEM_DIR / "milestone_state.json")
    wiped["milestone_state_removed"] = True

    _safe_rmtree(Paths.FORGE_DIR / "runs")
    wiped["runs_removed"] = True
    _safe_rmtree(Paths.BASE_DIR / ".artifacts")
    wiped["artifacts_removed"] = True

    for p in sorted(generated_files):
        _safe_unlink(p)

    # Always remove Forge-generated test modules under tests/forge_generated.
    fg = Paths.BASE_DIR / "tests" / "forge_generated"
    if fg.exists() and fg.is_dir():
        _safe_rmtree(fg)
        wiped["forge_generated_tests_removed"] = True

    # Also remove other likely-residue: `src/__pycache__` and empty init/test init.
    for extra in [
        Paths.BASE_DIR / "src" / "__init__.py",
        Paths.BASE_DIR / "tests" / "__init__.py",
    ]:
        _safe_unlink(extra)

    # Optionally remove artifacts/ directory used for execution/debug files.
    _safe_rmtree(Paths.ARTIFACTS_DIR)

    return wiped

