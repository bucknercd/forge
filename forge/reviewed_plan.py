from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Any

from forge.execution.models import ExecutionPlan
from forge.paths import Paths


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    return _sha256_text(path.read_text(encoding="utf-8"))


def plan_hash(plan: ExecutionPlan) -> str:
    canonical = json.dumps(plan.to_serializable(), sort_keys=True, separators=(",", ":"))
    return _sha256_text(canonical)


def reviewed_plan_dir() -> Path:
    return Paths.SYSTEM_DIR / "reviewed_plans"


def target_paths_for_plan(plan: ExecutionPlan) -> list[Path]:
    targets: list[Path] = []
    for a in plan.actions:
        t = type(a).__name__
        if t in {"ActionAppendSection", "ActionReplaceSection"}:
            target = getattr(a, "target")
            if target == "requirements":
                targets.append(Paths.REQUIREMENTS_FILE)
            elif target == "architecture":
                targets.append(Paths.ARCHITECTURE_FILE)
            elif target == "decisions":
                targets.append(Paths.DECISIONS_FILE)
            elif target == "milestones":
                targets.append(Paths.MILESTONES_FILE)
        elif t == "ActionAddDecision":
            targets.append(Paths.DECISIONS_FILE)
        elif t == "ActionMarkMilestoneCompleted":
            targets.append(Paths.MILESTONES_FILE)
    # Stable de-dupe preserve order
    out: list[Path] = []
    seen: set[str] = set()
    for p in targets:
        s = str(p)
        if s not in seen:
            seen.add(s)
            out.append(p)
    return out


def save_reviewed_plan(milestone_id: int, milestone_title: str, plan: ExecutionPlan) -> dict[str, Any]:
    reviewed_plan_dir().mkdir(parents=True, exist_ok=True)
    p_hash = plan_hash(plan)
    plan_id = f"m{milestone_id}-{p_hash[:12]}"
    targets = target_paths_for_plan(plan)
    targets_meta = [
        {
            "path": str(p),
            "rel_path": _rel(p),
            "hash": _file_hash(p),
        }
        for p in targets
    ]
    payload = {
        "plan_id": plan_id,
        "milestone_id": milestone_id,
        "milestone_title": milestone_title,
        "created_at": datetime.now().isoformat(),
        "plan_hash": p_hash,
        "milestones_file_hash": _file_hash(Paths.MILESTONES_FILE),
        "targets": targets_meta,
        "plan": plan.to_serializable(),
    }
    (reviewed_plan_dir() / f"{plan_id}.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    return payload


def load_reviewed_plan(plan_id: str) -> dict[str, Any] | None:
    path = reviewed_plan_dir() / f"{plan_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def validate_reviewed_plan(payload: dict[str, Any], current_plan: ExecutionPlan) -> tuple[bool, str]:
    expected = payload.get("plan_hash", "")
    current_hash = plan_hash(current_plan)
    if expected != current_hash:
        return False, "Reviewed plan no longer matches current milestone definition."
    stored_milestones_hash = payload.get("milestones_file_hash", "")
    if stored_milestones_hash != _file_hash(Paths.MILESTONES_FILE):
        return False, "Milestones file changed since plan review (stale reviewed plan)."
    for t in payload.get("targets", []):
        p = Path(t["path"])
        if _file_hash(p) != t.get("hash"):
            rel = t.get("rel_path") or str(p)
            return False, f"Target artifact changed since review: {rel}"
    return True, ""


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(Paths.BASE_DIR.resolve()).as_posix()
    except Exception:
        return str(path)
