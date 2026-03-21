"""Bounded relative paths for write_file and path_file_contains actions."""

from __future__ import annotations

from pathlib import Path

ALLOWED_REL_PREFIXES = ("examples/", "src/", "scripts/", "tests/")


def resolve_safe_project_path(rel: str, base_dir: Path) -> Path:
    """
    Resolve a repo-relative path under base_dir.
    Rejects traversal and restricts to allowed prefixes.
    """
    raw = rel.strip().replace("\\", "/").lstrip("/")
    if not raw or raw.startswith("..") or "/../" in f"/{raw}/":
        raise ValueError(f"Invalid or unsafe path: {rel!r}")
    parts = Path(raw).parts
    if ".." in parts:
        raise ValueError(f"Path traversal not allowed: {rel!r}")
    if not any(raw.startswith(p) for p in ALLOWED_REL_PREFIXES):
        raise ValueError(
            f"Path must start with one of {list(ALLOWED_REL_PREFIXES)}; got {rel!r}"
        )
    full = (base_dir / raw).resolve()
    base_resolved = base_dir.resolve()
    try:
        full.relative_to(base_resolved)
    except ValueError as exc:
        raise ValueError(f"Path escapes project root: {rel!r}") from exc
    return full
