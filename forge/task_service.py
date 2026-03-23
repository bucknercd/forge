"""
Task breakdown storage and bridge to milestone-shaped execution units.

Tasks live under ``.system/tasks/m<milestone_id>.json`` (inspectable JSON).
Execution still uses :class:`forge.design_manager.Milestone` shells so
:class:`forge.execution.plan.ExecutionPlanBuilder` and reviewed-plan apply
semantics stay unchanged.
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forge.design_manager import Milestone, MilestoneService
from forge.llm import LLMClient, StubLLMClient
from forge.llm_resolve import resolve_llm_client_from_policy
from forge.paths import Paths
from forge.policy_config import load_planner_policy
from forge.execution.parse import parse_forge_action_line
from forge.validation_normalize import sanitize_validation_rules

MIN_MULTI_TASKS = 2
MAX_TASKS = 6
_TASK_FILE_VERSION = 1

# Task status persisted in ``.system/tasks/m<id>.json``
TASK_STATUS_NOT_STARTED = "not_started"
TASK_STATUS_COMPLETED = "completed"


def task_is_completed(task: Task) -> bool:
    return (task.status or "").strip().lower() == TASK_STATUS_COMPLETED


def get_next_task(milestone_id: int) -> Task | None:
    """
    First task (by id) that is not completed and whose ``depends_on`` are all completed.

    Returns ``None`` when there are no tasks or every task is completed.
    """
    tasks = sorted(list_tasks(milestone_id), key=lambda t: t.id)
    if not tasks:
        return None
    done_ids = {t.id for t in tasks if task_is_completed(t)}
    for t in tasks:
        if task_is_completed(t):
            continue
        if not all(d in done_ids for d in t.depends_on):
            continue
        return t
    return None


def set_task_status(milestone_id: int, task_id: int, status: str) -> None:
    """Update one task's ``status`` and rewrite the tasks file."""
    tasks = list_tasks(milestone_id)
    updated: list[Task] = []
    found = False
    for t in tasks:
        if t.id == task_id:
            updated.append(
                Task(
                    id=t.id,
                    milestone_id=t.milestone_id,
                    title=t.title,
                    objective=t.objective,
                    summary=t.summary,
                    depends_on=list(t.depends_on),
                    files_allowed=t.files_allowed,
                    validation=t.validation,
                    done_when=t.done_when,
                    status=status,
                    milestone_context=t.milestone_context,
                    forge_actions=list(t.forge_actions),
                    forge_validation=list(t.forge_validation),
                )
            )
            found = True
        else:
            updated.append(t)
    if not found:
        return
    save_tasks(milestone_id, updated)


def all_tasks_completed(milestone_id: int) -> bool:
    tasks = list_tasks(milestone_id)
    return bool(tasks) and all(task_is_completed(t) for t in tasks)


def ensure_tasks_for_milestone(
    milestone_id: int,
    *,
    force: bool = False,
    log: Any | None = None,
) -> dict[str, Any]:
    """
    Ensure ``.system/tasks/m<id>.json`` exists with at least one task.

    If the file is missing or empty, runs the same expansion as ``task-expand``
    and optionally logs the standard auto-expand notice via ``log`` (default ``print``).
    """
    log_fn = log if log is not None else (lambda m: print(m, file=sys.stderr))
    path = tasks_file_for_milestone(milestone_id)
    existing = list_tasks(milestone_id) if path.exists() else []
    if existing and not force:
        return {
            "ok": True,
            "auto_expanded": False,
            "task_count": len(existing),
            "message": "",
        }

    log_fn(f"Tasks not found for milestone {milestone_id}. Auto-expanding tasks...")
    r = expand_milestone_to_tasks(milestone_id=milestone_id, force=force)
    if not r.get("ok"):
        return {**r, "auto_expanded": True}
    if r.get("expansion_mode") == "compatibility" and not r.get("skipped"):
        log_fn(
            "Task expansion used compatibility mode. Falling back to a single task mirroring the milestone."
        )
    return {
        **r,
        "auto_expanded": not bool(r.get("skipped")),
    }


def tasks_dir() -> Path:
    d = Paths.SYSTEM_DIR / "tasks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def tasks_file_for_milestone(milestone_id: int) -> Path:
    return tasks_dir() / f"m{milestone_id}.json"


@dataclass
class Task:
    """Execution-level unit under a parent milestone."""

    id: int
    milestone_id: int
    title: str
    objective: str
    summary: str
    depends_on: list[int] = field(default_factory=list)
    files_allowed: str | None = None
    validation: str = ""
    done_when: str = ""
    status: str = "not_started"
    milestone_context: str = ""
    forge_actions: list[str] = field(default_factory=list)
    forge_validation: list[str] = field(default_factory=list)

    def with_lines_tuples(self) -> tuple[list[tuple[int, str]], list[tuple[int, str]]]:
        return (
            [(0, a) for a in self.forge_actions],
            [(0, v) for v in self.forge_validation],
        )


def task_to_execution_milestone(parent: Milestone, task: Task) -> Milestone:
    """
    Build a :class:`Milestone` shaped object for planners/appliers.

    Uses the parent milestone id so ``mark_milestone_completed`` still targets
    the roadmap milestone in ``docs/milestones.md``.
    """
    awl, vwl = task.with_lines_tuples()
    return Milestone(
        id=parent.id,
        title=f"{parent.title} :: {task.title}",
        objective=task.objective,
        scope=task.summary or task.objective or parent.scope,
        validation=task.validation or parent.validation,
        summary=parent.summary,
        depends_on=list(parent.depends_on),
        forge_actions=list(task.forge_actions),
        forge_validation=list(task.forge_validation),
        forge_actions_with_lines=awl,
        forge_validation_with_lines=vwl,
    )


def _task_from_dict(milestone_id: int, data: dict[str, Any]) -> Task:
    forge_validation_raw = [str(x) for x in data.get("forge_validation", [])]
    forge_validation, _ = sanitize_validation_rules(forge_validation_raw, log_warnings=False)
    return Task(
        id=int(data["id"]),
        milestone_id=milestone_id,
        title=str(data.get("title", "")),
        objective=str(data.get("objective", "")),
        summary=str(data.get("summary", "")),
        depends_on=[int(x) for x in data.get("depends_on", [])],
        files_allowed=data.get("files_allowed"),
        validation=str(data.get("validation", "")),
        done_when=str(data.get("done_when", "")),
        status=str(data.get("status", "not_started")),
        milestone_context=str(data.get("milestone_context", "")),
        forge_actions=[str(x) for x in data.get("forge_actions", [])],
        forge_validation=forge_validation,
    )


def list_tasks(milestone_id: int) -> list[Task]:
    path = tasks_file_for_milestone(milestone_id)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks_raw = data.get("tasks", [])
    return [_task_from_dict(milestone_id, t) for t in tasks_raw]


def get_task(milestone_id: int, task_id: int) -> Task | None:
    for t in list_tasks(milestone_id):
        if t.id == task_id:
            return t
    return None


def task_count_for_milestone(milestone_id: int) -> int:
    return len(list_tasks(milestone_id))


def save_tasks(milestone_id: int, tasks: list[Task]) -> None:
    path = tasks_file_for_milestone(milestone_id)
    tasks_dir().mkdir(parents=True, exist_ok=True)
    payload = {
        "version": _TASK_FILE_VERSION,
        "milestone_id": milestone_id,
        "tasks": [
            {
                "id": t.id,
                "title": t.title,
                "objective": t.objective,
                "summary": t.summary,
                "depends_on": t.depends_on,
                "files_allowed": t.files_allowed,
                "validation": t.validation,
                "done_when": t.done_when,
                "status": t.status,
                "milestone_context": t.milestone_context,
                "forge_actions": t.forge_actions,
                "forge_validation": t.forge_validation,
            }
            for t in tasks
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


# --- Splitting / validation -------------------------------------------------


_MARK_COMPLETED = "mark_milestone_completed"


def _partition_actions(actions: list[str]) -> tuple[list[str], list[str]]:
    work: list[str] = []
    marks: list[str] = []
    for a in actions:
        if a.strip() == _MARK_COMPLETED:
            marks.append(a)
        else:
            work.append(a)
    return work, marks


def _split_evenly(items: list[str], n_chunks: int) -> list[list[str]]:
    if n_chunks <= 0:
        return []
    if not items:
        return [[] for _ in range(n_chunks)]
    n_chunks = min(n_chunks, len(items)) or 1
    base, rem = divmod(len(items), n_chunks)
    out: list[list[str]] = []
    i = 0
    for c in range(n_chunks):
        take = base + (1 if c < rem else 0)
        out.append(items[i : i + take])
        i += take
    return out


def _milestone_short_name(parent: Milestone) -> str:
    t = parent.title
    if ":" in t:
        return t.split(":", 1)[-1].strip() or t.strip()
    return t.strip() or f"Milestone {parent.id}"


def _title_from_actions(chunk: list[str], parent: Milestone, index: int, *, final: bool) -> str:
    if final:
        return f"Finalize: validation and milestone completion ({_milestone_short_name(parent)})"
    if not chunk:
        return f"Setup work {index} ({_milestone_short_name(parent)})"
    first = chunk[0].strip()
    if len(first) > 72:
        first = first[:69] + "..."
    verb = first.split(None, 1)[0].lower() if first else "apply"
    return f"{verb.title()} step {index}: {first}"[:120]


def _objective_for_chunk(
    chunk: list[str],
    parent: Milestone,
    index: int,
    *,
    final: bool,
) -> str:
    if final:
        return (
            f"Run milestone validation rules and complete the milestone marker for "
            f"'{_milestone_short_name(parent)}' after prior tasks."
        )
    if not chunk:
        return (
            f"Prepare context for milestone '{_milestone_short_name(parent)}' "
            f"(objective: {parent.objective[:200]})"
        )
    lines = "; ".join(c.strip()[:80] for c in chunk[:3])
    if len(chunk) > 3:
        lines += "; …"
    return (
        f"Execute bounded Forge actions for this slice of milestone "
        f"'{_milestone_short_name(parent)}': {lines}"
    )


def _summary_for_chunk(parent: Milestone, index: int, total: int, *, final: bool) -> str:
    scope_hint = (parent.summary or parent.scope or "")[:160]
    if final:
        return (
            f"Last of {total} tasks: apply completion marker and repo checks. "
            f"Scope context: {scope_hint}"
        )
    return (
        f"Task {index} of {total} for this milestone. "
        f"Depends on prior tasks completing. Context: {scope_hint}"
    )


def _duplicate_validations(parent: Milestone) -> list[str]:
    return list(parent.forge_validation)


def _dependencies_acyclic(tasks: list[Task]) -> bool:
    ids = {t.id for t in tasks}
    graph = {t.id: list(t.depends_on) for t in tasks}

    def dfs(n: int, visiting: set[int], visited: set[int]) -> bool:
        if n in visiting:
            return False
        if n in visited:
            return True
        visiting.add(n)
        for d in graph.get(n, []):
            if d not in ids:
                return False
            if not dfs(d, visiting, visited):
                return False
        visiting.remove(n)
        visited.add(n)
        return True

    visited: set[int] = set()
    for t in tasks:
        if not dfs(t.id, set(), visited):
            return False
    return True


def validate_task_list(
    tasks: list[Task], *, require_multi: bool = True
) -> tuple[bool, str]:
    """
    Validate tasks before persistence.

    When ``require_multi``, enforce 2..MAX_TASKS tasks and full field checks.
    Single-task lists skip the multi count rule (compatibility mode).
    """
    if not tasks:
        return False, "No tasks."
    if require_multi:
        if len(tasks) < MIN_MULTI_TASKS:
            return False, f"Need at least {MIN_MULTI_TASKS} tasks, got {len(tasks)}."
        if len(tasks) > MAX_TASKS:
            return False, f"At most {MAX_TASKS} tasks, got {len(tasks)}."

    seen: set[int] = set()
    for t in tasks:
        if t.id in seen:
            return False, f"Duplicate task id {t.id}."
        seen.add(t.id)

    expected_ids = set(range(1, len(tasks) + 1))
    if seen != expected_ids:
        return False, f"Task ids must be 1..{len(tasks)} exactly, got {sorted(seen)}."

    for t in tasks:
        if not t.title.strip() or len(t.title.strip()) < 8:
            return False, f"Task {t.id} title too short or empty."
        if not t.objective.strip():
            return False, f"Task {t.id} missing objective."
        if not t.summary.strip():
            return False, f"Task {t.id} missing summary."
        if not t.validation.strip():
            return False, f"Task {t.id} missing validation text."
        if not t.done_when.strip():
            return False, f"Task {t.id} missing done_when."
        for d in t.depends_on:
            if d not in expected_ids or d >= t.id:
                return False, f"Task {t.id} has invalid depends_on {t.depends_on}."
        if t.forge_actions and not t.forge_validation:
            return (
                False,
                f"Task {t.id} has Forge Actions but no Forge Validation lines.",
            )
        vague = re.compile(r"^implement\s+feature\b", re.I)
        if vague.match(t.title.strip()):
            return False, f"Task {t.id} title is too vague."

    if not _dependencies_acyclic(tasks):
        return False, "Task dependency graph has a cycle or invalid edge."

    return True, ""


def split_actions_into_tasks(parent: Milestone, milestone_id: int) -> list[Task]:
    """
    Deterministic 2–6 tasks: split ``mark_milestone_completed`` onto the last task only;
    distribute other actions across preceding tasks; linear dependency chain.

    Milestones with work actions but **no** ``mark_milestone_completed`` are split across
    2–6 tasks with Forge Validation duplicated on each slice (same rules as the parent).

    Returns an empty list when multi-task expansion is not possible (caller uses compat).
    """
    work, marks = _partition_actions(list(parent.forge_actions))
    vals = _duplicate_validations(parent)
    short = _milestone_short_name(parent)

    # Nothing to split: caller should use compatibility mode
    if not work and not vals and not marks:
        return []

    # Any task with Forge Actions must have Forge Validation lines
    if (work or marks) and not vals:
        return []

    wlen = len(work)

    # Only completion marker + validation (no prior work actions)
    if wlen == 0:
        tasks: list[Task] = [
            Task(
                id=1,
                milestone_id=milestone_id,
                title=f"Prepare milestone context: {short}"[:120],
                objective=(
                    f"Review objective and scope for '{short}' before running "
                    f"completion actions: {parent.objective[:300]}"
                ),
                summary=(parent.summary or parent.scope or parent.objective)[:400],
                depends_on=[],
                validation=parent.validation,
                done_when="Context reviewed; ready for completion task.",
                status="not_started",
                forge_actions=[],
                forge_validation=[],
            ),
            Task(
                id=2,
                milestone_id=milestone_id,
                title=f"Finalize: {short}"[:120],
                objective="Apply milestone completion marker and repository validation rules.",
                summary="Runs Forge Validation from the milestone and mark_milestone_completed.",
                depends_on=[1],
                validation=parent.validation,
                done_when="All Forge Validation rules pass and milestone marker applied.",
                status="not_started",
                forge_actions=list(marks),
                forge_validation=list(vals),
            ),
        ]
        return tasks

    # Work without mark_milestone_completed: split work only (2..MAX_TASKS tasks)
    if not marks:
        if wlen < 2:
            return []
        n_chunks = min(MAX_TASKS, max(MIN_MULTI_TASKS, math.ceil(wlen / 2)))
        n_chunks = min(n_chunks, wlen)
        chunks = _split_evenly(work, n_chunks)
        total = len(chunks)
        tasks_out: list[Task] = []
        for i, chunk in enumerate(chunks, start=1):
            tid = i
            deps = [tid - 1] if tid > 1 else []
            tasks_out.append(
                Task(
                    id=tid,
                    milestone_id=milestone_id,
                    title=_title_from_actions(chunk, parent, i, final=False),
                    objective=_objective_for_chunk(chunk, parent, i, final=False),
                    summary=_summary_for_chunk(parent, i, total, final=False),
                    depends_on=deps,
                    validation=parent.validation,
                    done_when=f"Forge actions for slice {i} applied; ready for next task.",
                    status="not_started",
                    forge_actions=list(chunk),
                    forge_validation=list(vals),
                )
            )
        return tasks_out

    # Work + completion marker: work chunks + one finalizer task
    max_work_slots = min(MAX_TASKS - 1, max(1, math.ceil(wlen / 2)))
    n_work = min(max_work_slots, wlen)
    chunks = _split_evenly(work, n_work)
    total = len(chunks) + 1

    tasks_out = []
    tid = 1
    for i, chunk in enumerate(chunks, start=1):
        deps = [tid - 1] if tid > 1 else []
        tasks_out.append(
            Task(
                id=tid,
                milestone_id=milestone_id,
                title=_title_from_actions(chunk, parent, i, final=False),
                objective=_objective_for_chunk(chunk, parent, i, final=False),
                summary=_summary_for_chunk(parent, i, total, final=False),
                depends_on=deps,
                validation=parent.validation,
                done_when=f"Forge actions for slice {i} applied; ready for next task.",
                status="not_started",
                forge_actions=list(chunk),
                forge_validation=list(vals),
            )
        )
        tid += 1

    tasks_out.append(
        Task(
            id=tid,
            milestone_id=milestone_id,
            title=_title_from_actions([], parent, tid, final=True),
            objective=_objective_for_chunk([], parent, tid, final=True),
            summary=_summary_for_chunk(parent, tid, total, final=True),
            depends_on=[tid - 1] if tid > 1 else [],
            validation=parent.validation,
            done_when="Milestone validation rules pass and completion marker applied.",
            status="not_started",
            forge_actions=list(marks),
            forge_validation=list(vals),
        )
    )

    return tasks_out


def _try_llm_expand_tasks(parent: Milestone, milestone_id: int, client: LLMClient) -> list[Task] | None:
    if isinstance(client, StubLLMClient):
        return None
    prompt = (
        "You split a Forge milestone into 2–6 concrete engineering tasks.\n"
        "Return ONLY JSON (no markdown fences) with this exact shape:\n"
        '{"tasks":[{"id":1,"title":"...","objective":"...","summary":"...",'
        '"depends_on":[],"validation":"...","done_when":"...",'
        '"forge_actions":["action line", "..."],"forge_validation":["rule line"]}]}\n\n'
        "Rules:\n"
        "- ids must be 1..N contiguous; depends_on only reference lower ids; acyclic.\n"
        "- Each task title must be specific (not 'Implement feature').\n"
        "- forge_actions: same syntax as Forge milestone actions (strings).\n"
        "- Put mark_milestone_completed only on the LAST task if the milestone uses it.\n"
        "- forge_validation on any task with non-empty forge_actions.\n\n"
        f"Milestone title: {parent.title}\n"
        f"Objective: {parent.objective}\n"
        f"Summary/scope: {parent.summary or parent.scope}\n"
        f"Forge Actions:\n"
        + "\n".join(f"  - {a}" for a in parent.forge_actions)
        + "\nForge Validation:\n"
        + "\n".join(f"  - {v}" for v in parent.forge_validation)
    )
    try:
        raw = client.generate(prompt)
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    raw_tasks = data.get("tasks")
    if not isinstance(raw_tasks, list):
        return None
    out: list[Task] = []
    for item in raw_tasks:
        if not isinstance(item, dict):
            return None
        try:
            raw_fv = [str(x) for x in item.get("forge_validation", [])]
            norm_fv, _ = sanitize_validation_rules(raw_fv, log_warnings=True)
            out.append(
                Task(
                    id=int(item["id"]),
                    milestone_id=milestone_id,
                    title=str(item.get("title", "")),
                    objective=str(item.get("objective", "")),
                    summary=str(item.get("summary", "")),
                    depends_on=[int(x) for x in item.get("depends_on", [])],
                    files_allowed=item.get("files_allowed"),
                    validation=str(item.get("validation", "")),
                    done_when=str(item.get("done_when", "")),
                    status=str(item.get("status", "not_started")),
                    forge_actions=[str(x) for x in item.get("forge_actions", [])],
                    forge_validation=norm_fv,
                )
            )
        except (KeyError, TypeError, ValueError):
            return None
    return out if out else None


def _compat_single_task(parent: Milestone, milestone_id: int) -> list[Task]:
    title_line = parent.title
    if ":" in title_line:
        short_title = title_line.split(":", 1)[-1].strip()
    else:
        short_title = title_line.strip()
    compat_title = short_title or f"Milestone {milestone_id} work"
    if len(compat_title.strip()) < 8:
        compat_title = f"Milestone {milestone_id} work — {compat_title}".strip()[:120]
    return [
        Task(
            id=1,
            milestone_id=milestone_id,
            title=compat_title,
            objective=parent.objective,
            summary=parent.summary or parent.scope,
            depends_on=[],
            files_allowed=None,
            validation=parent.validation,
            done_when=parent.validation,
            status="not_started",
            forge_actions=list(parent.forge_actions),
            forge_validation=list(parent.forge_validation),
        )
    ]


_PSEUDO_ACTION_VERBS = {
    "create_file",
    "modify_file",
    "update_file",
    "edit_file",
}

_BEHAVIOR_TERMS = (
    "parse",
    "count",
    "filter",
    "ignore",
    "aggregate",
    "sort",
    "top 5",
    "error",
    "debug",
    "info",
)

_SETUP_ONLY_TERMS = (
    "sample",
    "setup",
    "scaffold",
    "bootstrap",
    "placeholder",
    "readme",
    "documentation",
    "docs",
)


def _parent_behavior_heavy(parent: Milestone) -> bool:
    blob = " ".join(
        (
            parent.title or "",
            parent.objective or "",
            parent.scope or "",
            parent.validation or "",
            parent.summary or "",
        )
    ).lower()
    return any(t in blob for t in _BEHAVIOR_TERMS)


def _task_has_behavior_signal(t: Task) -> bool:
    blob = " ".join((t.title or "", t.objective or "", t.summary or "", t.validation or "")).lower()
    return any(tok in blob for tok in _BEHAVIOR_TERMS)


def _task_is_setup_only(t: Task) -> bool:
    blob = " ".join((t.title or "", t.objective or "", t.summary or "")).lower()
    has_setup = any(tok in blob for tok in _SETUP_ONLY_TERMS)
    return has_setup and not _task_has_behavior_signal(t)


def _enforce_behavior_heavy_early_task_expectation(
    parent: Milestone, tasks: list[Task]
) -> tuple[bool, str]:
    if not tasks:
        return False, "No tasks to evaluate."
    if not _parent_behavior_heavy(parent):
        return True, ""
    first = tasks[0]
    first_two = tasks[:2]
    if _task_is_setup_only(first):
        return False, "Behavior-heavy milestone decomposed into setup-only first task."
    if not any(_task_has_behavior_signal(t) for t in first_two):
        return (
            False,
            "Behavior-heavy milestone lost semantic intent in early tasks "
            "(first two tasks lack parse/count/filter/top-k behavior signals).",
        )
    return True, ""


def _attach_parent_behavior_context(parent: Milestone, tasks: list[Task]) -> None:
    ctx = (
        f"title: {parent.title}\n"
        f"objective: {parent.objective}\n"
        f"scope: {parent.scope}\n"
        f"validation: {parent.validation}\n"
    ).strip()
    for t in tasks:
        t.milestone_context = ctx


def _sanitize_task_forge_actions(parent: Milestone, tasks: list[Task]) -> dict[str, Any]:
    """
    Strip pseudo/invalid embedded forge actions so tasks remain spec-like.

    We validate embedded actions by round-tripping them through the existing
    deterministic Forge parser (parse_forge_action_line). Invalid lines are
    removed before tasks are persisted.
    """

    invalid_dropped: list[dict[str, str]] = []
    for t in tasks:
        if not t.forge_actions:
            continue
        kept: list[str] = []
        for raw in t.forge_actions:
            a = (raw or "").strip()
            if not a:
                continue
            verb = a.split(None, 1)[0].lower()
            if verb in _PSEUDO_ACTION_VERBS:
                invalid_dropped.append({"task_id": str(t.id), "action": a, "reason": "pseudo_action"})
                continue
            try:
                # Validate canonical syntax deterministically. We discard the parsed
                # object; we only care that parsing succeeds.
                parse_forge_action_line(a, parent, line_no=None)
            except ValueError as exc:
                invalid_dropped.append(
                    {
                        "task_id": str(t.id),
                        "action": a,
                        "reason": f"invalid_forge_action: {exc}",
                    }
                )
                continue
            kept.append(a)
        t.forge_actions = kept

    return {"invalid_actions_dropped": invalid_dropped, "task_count": len(tasks)}


def _clear_forge_actions_for_llm_tasks(mode: str, tasks: list[Task]) -> int:
    """
    For LLM-generated vertical slices we keep tasks spec-driven.
    Execution must be handled by the planner, not embedded in tasks.
    """

    if mode != "llm_multi":
        return 0
    cleared = 0
    for t in tasks:
        if t.forge_actions:
            cleared += len(t.forge_actions)
        t.forge_actions = []
    return cleared


def expand_milestone_to_tasks(*, milestone_id: int, force: bool = False) -> dict[str, Any]:
    """
    Ensure milestone ``milestone_id`` has a task breakdown.

    Produces **2–6 deterministic tasks** when the milestone has splittable Forge
    Actions / Validation. Falls back to a **single compatibility task** if
    validation fails or there is nothing to split.

    When ``forge-policy.json`` configures a non-stub OpenAI client, an optional
    LLM pass may replace the deterministic list if it passes the same validation.
    """
    parent = MilestoneService.get_milestone(milestone_id)
    if not parent:
        return {"ok": False, "message": f"Unknown milestone id {milestone_id}."}
    path = tasks_file_for_milestone(milestone_id)
    if path.exists() and not force:
        existing = list_tasks(milestone_id)
        if existing:
            return {
                "ok": True,
                "message": (
                    f"Tasks already exist for milestone {milestone_id} "
                    f"({len(existing)} task(s)). Use --force to replace from the "
                    "current milestone definition."
                ),
                "task_count": len(existing),
                "skipped": True,
            }

    mode = "compatibility"
    chosen: list[Task] = []

    det = split_actions_into_tasks(parent, milestone_id)
    ok_det, err_det = (
        validate_task_list(det, require_multi=True) if det else (False, "empty deterministic")
    )
    if ok_det:
        chosen = det
        mode = "deterministic_multi"
    else:
        policy, perr = load_planner_policy()
        if not perr and policy.llm_client:
            client, cerr = resolve_llm_client_from_policy(policy)
            if not cerr and client is not None:
                llm_tasks = _try_llm_expand_tasks(parent, milestone_id, client)
                if llm_tasks:
                    ok_llm, _ = validate_task_list(llm_tasks, require_multi=True)
                    ok_behavior, _ = _enforce_behavior_heavy_early_task_expectation(
                        parent, llm_tasks
                    )
                    if ok_llm and ok_behavior:
                        chosen = llm_tasks
                        mode = "llm_multi"

    if not chosen:
        chosen = _compat_single_task(parent, milestone_id)
        mode = "compatibility"
        ok_c, err_c = validate_task_list(chosen, require_multi=False)
        if not ok_c:
            return {"ok": False, "message": f"Compatibility task invalid: {err_c}"}

    # Safety: tasks must never persist unsupported pseudo-actions.
    # Also make LLM-expanded tasks spec-only by default.
    _attach_parent_behavior_context(parent, chosen)
    sanitize_res = _sanitize_task_forge_actions(parent, chosen)
    llm_cleared = _clear_forge_actions_for_llm_tasks(mode, chosen)

    save_tasks(milestone_id, chosen)
    try:
        rel = path.relative_to(Paths.BASE_DIR).as_posix()
    except ValueError:
        rel = str(path)

    msg = (
        f"Expanded milestone {milestone_id} into {len(chosen)} task(s) "
        f"({mode}). See `{rel}`."
    )
    if mode == "compatibility":
        msg += " (fallback: single task mirroring the milestone; split manually if needed.)"

    return {
        "ok": True,
        "message": msg,
        "task_count": len(chosen),
        "skipped": False,
        "tasks_path": str(path),
        "expansion_mode": mode,
        "invalid_actions_dropped": len(sanitize_res.get("invalid_actions_dropped") or []),
        "llm_actions_cleared": llm_cleared,
    }
