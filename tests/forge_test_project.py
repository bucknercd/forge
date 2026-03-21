"""Helpers for setting up a minimal Forge project tree in tests."""

from __future__ import annotations

from forge.paths import Paths


def forge_block(marker: str) -> str:
    """Minimal forge actions + validation that touch requirements.md deterministically."""
    return f"""- **Forge Actions**:
  - append_section requirements Overview | {marker}
  - mark_milestone_completed
- **Forge Validation**:
  - file_contains requirements {marker}
"""


def configure_project(tmp_path, milestones_body: str) -> None:
    Paths.refresh(tmp_path)
    Paths.DOCS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
    Paths.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    Paths.REQUIREMENTS_FILE.write_text(
        "# Requirements\n\n## Overview\n\nBase content.\n",
        encoding="utf-8",
    )
    Paths.ARCHITECTURE_FILE.write_text(
        "# Architecture\n\n## Design\n\nBase content.\n",
        encoding="utf-8",
    )
    Paths.DECISIONS_FILE.write_text("# Decisions\n\n## Log\n\n", encoding="utf-8")
    Paths.RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    Paths.RUN_HISTORY_FILE.touch()
    Paths.MILESTONES_FILE.write_text(milestones_body, encoding="utf-8")
