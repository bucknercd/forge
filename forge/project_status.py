from pathlib import Path

from forge.paths import Paths
from forge.project_templates import starter_templates


def _normalize_text(text: str) -> str:
    return text.strip().replace("\r\n", "\n")


def analyze_project_status() -> dict:
    """
    Analyze current project readiness.

    States:
    - not_initialized: required dirs/files are missing
    - initialized_incomplete: initialized but weak/missing meaningful content
    - ready: initialized and minimally usable
    """
    is_valid, missing = Paths.project_validation()
    templates = starter_templates()

    missing_paths = [str(p) for p in missing]
    empty_files: list[str] = []
    template_only_files: list[str] = []

    key_docs: list[Path] = [
        Paths.VISION_FILE,
        Paths.REQUIREMENTS_FILE,
        Paths.ARCHITECTURE_FILE,
        Paths.DECISIONS_FILE,
        Paths.MILESTONES_FILE,
    ]

    for file_path in key_docs:
        if not file_path.exists():
            continue
        content = file_path.read_text(encoding="utf-8")
        if not content.strip():
            empty_files.append(str(file_path))
            continue
        template = templates.get(file_path.name)
        if template is not None and _normalize_text(content) == _normalize_text(template):
            template_only_files.append(str(file_path))

    milestones_issue = False
    if Paths.MILESTONES_FILE.exists():
        milestones_text = Paths.MILESTONES_FILE.read_text(encoding="utf-8")
        # At least one recognized milestone heading should exist.
        milestones_issue = "## Milestone" not in milestones_text

    content_issues = bool(empty_files or template_only_files or milestones_issue)

    if not is_valid:
        state = "not_initialized"
    elif content_issues:
        state = "initialized_incomplete"
    else:
        state = "ready"

    return {
        "state": state,
        "missing_paths": missing_paths,
        "empty_files": empty_files,
        "template_only_files": template_only_files,
        "milestones_issue": milestones_issue,
    }

