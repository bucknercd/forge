"""Markdown section helpers (## headings)."""

from __future__ import annotations

import re


def _normalize_heading(text: str) -> str:
    return " ".join(text.strip().split())


def find_section_bounds(content: str, section_heading: str) -> tuple[int, int] | None:
    """
    Return [start, end) slice indices for the body of `## {section_heading}`.
    End is the start of the next ## heading or len(content).
    """
    h = _normalize_heading(section_heading)
    pattern = re.compile(rf"(?m)^##\s+{re.escape(h)}\s*$")
    m = pattern.search(content)
    if not m:
        return None
    start_body = content.find("\n", m.end())
    if start_body == -1:
        start_body = len(content)
    else:
        start_body += 1

    next_heading = re.search(r"(?m)^##\s+", content[start_body:])
    if next_heading:
        end = start_body + next_heading.start()
    else:
        end = len(content)
    return start_body, end


def append_to_section(content: str, section_heading: str, body: str) -> tuple[str, bool]:
    """
    Append `body` (trimmed) to the section under `## section_heading`.
    If the section is missing, append a new section at EOF.
    Idempotent: if body is already present anywhere in the file, no-op (returns changed=False).
    """
    text = body.strip()
    if not text:
        return content, False
    if text in content:
        return content, False

    h = _normalize_heading(section_heading)
    bounds = find_section_bounds(content, section_heading)
    if bounds is None:
        insertion = f"\n## {h}\n\n{text}\n"
        return content.rstrip() + insertion + ("" if content.endswith("\n") else "\n"), True

    start_body, end = bounds
    insert = f"{text}\n"
    new_content = content[:end].rstrip() + "\n\n" + insert + content[end:]
    return new_content, True


def replace_section_body(content: str, section_heading: str, body: str) -> tuple[str, bool]:
    """Replace everything inside the section (between its ## and the next ##)."""
    text = body.strip()
    bounds = find_section_bounds(content, section_heading)
    if bounds is None:
        h = _normalize_heading(section_heading)
        block = f"\n## {h}\n\n{text}\n"
        return content.rstrip() + block + "\n", True

    start_body, end = bounds
    old_inner = content[start_body:end]
    new_inner = text + ("\n" if text and not text.endswith("\n") else "")
    if old_inner.strip() == new_inner.strip():
        return content, False
    new_content = content[:start_body] + new_inner + content[end:]
    return new_content, True


def read_section_body(content: str, section_heading: str) -> str | None:
    bounds = find_section_bounds(content, section_heading)
    if bounds is None:
        return None
    start_body, end = bounds
    return content[start_body:end]


def insert_milestone_forge_status_completed(content: str, milestone_id: int) -> tuple[str, bool]:
    """
    Append `- **Forge Status**: completed` inside the ## Milestone N block if missing.
    """
    marker = "- **Forge Status**: completed"
    block_re = re.compile(
        rf"(?ms)^##\s+Milestone\s+{milestone_id}\s*:\s*.+?(?=^##\s+Milestone\s+\d+|\Z)"
    )
    m = block_re.search(content)
    if not m:
        return content, False
    block = m.group(0)
    if marker in block:
        return content, False
    updated_block = block.rstrip() + "\n" + marker + "\n"
    return content[: m.start()] + updated_block + content[m.end() :], True
