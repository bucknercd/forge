"""
Narrow sync from explicit prompt-task completion to docs/milestones.md.

Only the milestone ``Status:`` line and checkbox lines inside the managed
``<!-- FORGE:STATUS START -->`` / ``<!-- FORGE:STATUS END -->`` block are
modified. All other bytes are preserved (line-based reconstruction).
"""

from __future__ import annotations

import re

from forge.paths import Paths

FORGE_STATUS_START = "<!-- FORGE:STATUS START -->"
FORGE_STATUS_END = "<!-- FORGE:STATUS END -->"

STATUS_NOT_STARTED = "not started"
STATUS_IN_PROGRESS = "in progress"
STATUS_COMPLETED = "completed"

_MILESTONE_HEADING_RE = re.compile(r"^##\s+Milestone\b")
_CHECKBOX_RE = re.compile(r"^(\s*)(\*|\-)(\s+)\[([ xX])\](\s*)(.*)$")
_STATUS_RE = re.compile(r"^Status:\s*.*$")


class MilestoneStatusSyncError(ValueError):
    """Raised when milestones.md cannot be updated safely for the target milestone."""


def _norm_label(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def milestone_section_ranges(lines: list[str]) -> list[tuple[int, int]]:
    """1-based milestone index matches Forge milestone_id: first section is id 1."""
    starts: list[int] = []
    for i, line in enumerate(lines):
        if _MILESTONE_HEADING_RE.match(line.strip()):
            starts.append(i)
    ranges: list[tuple[int, int]] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        ranges.append((start, end))
    return ranges


def _section_bounds(lines: list[str], milestone_id: int) -> tuple[int, int]:
    ranges = milestone_section_ranges(lines)
    if not ranges:
        raise MilestoneStatusSyncError(
            "No ## Milestone sections found in docs/milestones.md; cannot sync status."
        )
    if milestone_id < 1 or milestone_id > len(ranges):
        raise MilestoneStatusSyncError(
            f"Milestone id {milestone_id} does not match any unique section "
            f"(found {len(ranges)} milestone section(s) in order). "
            "Use milestone ids 1..N in document order."
        )
    return ranges[milestone_id - 1]


def milestone_section_has_managed_block(lines: list[str], milestone_id: int) -> bool:
    """True if the Nth milestone section contains ``FORGE:STATUS START`` (opt-in surface)."""
    sec_start, sec_end = _section_bounds(lines, milestone_id)
    for i in range(sec_start, sec_end):
        if lines[i].strip() == FORGE_STATUS_START:
            return True
    return False


def _find_managed_block(
    lines: list[str], sec_start: int, sec_end: int, milestone_id: int
) -> tuple[int, int]:
    block_start: int | None = None
    block_end: int | None = None
    for i in range(sec_start, sec_end):
        stripped = lines[i].strip()
        if stripped == FORGE_STATUS_START:
            if block_start is not None:
                raise MilestoneStatusSyncError(
                    f"Milestone {milestone_id}: duplicate {FORGE_STATUS_START!r} in section."
                )
            block_start = i
        elif stripped == FORGE_STATUS_END:
            if block_start is None:
                raise MilestoneStatusSyncError(
                    f"Milestone {milestone_id}: {FORGE_STATUS_END!r} appears before "
                    f"{FORGE_STATUS_START!r}."
                )
            block_end = i
            break
    if block_start is None or block_end is None or block_end <= block_start:
        raise MilestoneStatusSyncError(
            f"Milestone {milestone_id}: add a managed status block:\n"
            f"  {FORGE_STATUS_START}\n"
            f"  * [ ] Task …\n"
            f"  {FORGE_STATUS_END}\n"
            "Forge only edits lines inside this block plus the section Status: line."
        )
    return block_start, block_end


def _find_status_line_index(
    lines: list[str],
    sec_start: int,
    sec_end: int,
    block_start: int,
    block_end: int,
    milestone_id: int,
) -> int:
    """Status line must lie in the milestone section and not inside the managed block."""
    status_idx: int | None = None
    for i in range(sec_start, sec_end):
        if block_start <= i <= block_end:
            continue
        if _STATUS_RE.match(lines[i]):
            if status_idx is not None:
                raise MilestoneStatusSyncError(
                    f"Milestone {milestone_id}: multiple Status: lines in section; "
                    "keep exactly one outside the FORGE status block."
                )
            status_idx = i
    if status_idx is None:
        raise MilestoneStatusSyncError(
            f"Milestone {milestone_id}: missing Status: line "
            "(expected e.g. 'Status: not started' outside the FORGE status block)."
        )
    return status_idx


def _checkbox_indices_in_block(
    lines: list[str], block_start: int, block_end: int, milestone_id: int
) -> list[int]:
    indices: list[int] = []
    for i in range(block_start + 1, block_end):
        line = lines[i]
        if line.strip() == "":
            continue
        if _CHECKBOX_RE.match(line):
            indices.append(i)
            continue
        raise MilestoneStatusSyncError(
            f"Milestone {milestone_id}: inside the FORGE status block, only blank lines "
            f"and markdown task items (* [ ] / - [ ]) are allowed; got: {line!r}"
        )
    if not indices:
        raise MilestoneStatusSyncError(
            f"Milestone {milestone_id}: FORGE status block has no checkbox lines "
            "(* [ ] or - [ ])."
        )
    return indices


def _resolve_target_checkbox_index(
    cb_line_indices: list[int],
    lines: list[str],
    milestone_task_id: int | None,
    task_title: str,
    milestone_id: int,
) -> int:
    """Return index into ``cb_line_indices`` (0-based)."""
    if milestone_task_id is not None:
        k = int(milestone_task_id) - 1
        if k < 0 or k >= len(cb_line_indices):
            raise MilestoneStatusSyncError(
                f"Milestone {milestone_id}: milestone task id {milestone_task_id} does not map to "
                f"a checkbox (found {len(cb_line_indices)} checkbox line(s), 1-based order)."
            )
        return k
    title = _norm_label(task_title)
    if not title:
        raise MilestoneStatusSyncError(
            f"Milestone {milestone_id}: cannot match checkbox (missing milestone task id and title)."
        )
    matches: list[int] = []
    for idx, line_i in enumerate(cb_line_indices):
        m = _CHECKBOX_RE.match(lines[line_i])
        assert m is not None
        if _norm_label(m.group(6)) == title:
            matches.append(idx)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise MilestoneStatusSyncError(
            f"Milestone {milestone_id}: no checkbox label matches task title {task_title!r}."
        )
    raise MilestoneStatusSyncError(
        f"Milestone {milestone_id}: multiple checkboxes match task title {task_title!r}; "
        "use distinct labels or ensure milestone task ids are set."
    )


def _derive_status(checked: int, total: int) -> str:
    if checked == 0:
        return STATUS_NOT_STARTED
    if checked == total:
        return STATUS_COMPLETED
    return STATUS_IN_PROGRESS


def _set_checkbox_checked(line: str) -> str:
    m = _CHECKBOX_RE.match(line)
    if not m:
        raise MilestoneStatusSyncError(f"Internal error: expected checkbox line, got {line!r}")
    return m.group(1) + m.group(2) + m.group(3) + "[x]" + m.group(5) + m.group(6)


def update_milestones_md_for_task_completion(
    content: str,
    *,
    milestone_id: int,
    milestone_task_id: int | None,
    task_title: str,
) -> str:
    """
    Mark the checkbox for the completed task and recompute ``Status:`` for that milestone.

    * Checkbox selection uses 1-based ``milestone_task_id`` matching checkbox order in the
      block, or exact normalized label match on ``task_title`` when ``milestone_task_id`` is None.
    """
    lines = content.split("\n")
    sec_start, sec_end = _section_bounds(lines, milestone_id)
    block_start, block_end = _find_managed_block(lines, sec_start, sec_end, milestone_id)
    status_idx = _find_status_line_index(
        lines, sec_start, sec_end, block_start, block_end, milestone_id
    )
    cb_indices = _checkbox_indices_in_block(lines, block_start, block_end, milestone_id)
    pick = _resolve_target_checkbox_index(
        cb_indices, lines, milestone_task_id, task_title, milestone_id
    )
    target_line_idx = cb_indices[pick]

    new_lines = list(lines)
    new_lines[target_line_idx] = _set_checkbox_checked(new_lines[target_line_idx])

    checked = 0
    for idx in cb_indices:
        m = _CHECKBOX_RE.match(new_lines[idx])
        assert m is not None
        if m.group(4).strip().lower() == "x":
            checked += 1
    total = len(cb_indices)
    new_status = _derive_status(checked, total)
    new_lines[status_idx] = f"Status: {new_status}"

    return "\n".join(new_lines)


def sync_milestones_md_for_completed_prompt_task(
    *,
    milestone_id: int | None,
    milestone_task_id: int | None,
    task_title: str,
) -> None:
    """Write docs/milestones.md after a task has been marked completed in machine state."""
    if milestone_id is None:
        return
    path = Paths.MILESTONES_FILE
    if not path.exists():
        raise MilestoneStatusSyncError(
            "docs/milestones.md is missing; add the file and a managed status block, or skip sync."
        )
    raw = path.read_text(encoding="utf-8")
    lines = raw.split("\n")
    if not milestone_section_has_managed_block(lines, int(milestone_id)):
        return
    new = update_milestones_md_for_task_completion(
        raw,
        milestone_id=int(milestone_id),
        milestone_task_id=int(milestone_task_id) if milestone_task_id is not None else None,
        task_title=task_title,
    )
    if new == raw:
        return
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new, encoding="utf-8")
    tmp.replace(path)
