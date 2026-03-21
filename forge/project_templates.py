def starter_templates() -> dict[str, str]:
    """
    Minimal starter templates for new Forge project documents.
    Keys are logical document names used by Paths.initialize_project().
    """
    return {
        "vision.txt": (
            "Project Vision\n"
            "=============\n\n"
            "Describe the core problem, target users, and intended outcome.\n"
        ),
        "requirements.md": (
            "# Requirements\n\n"
            "- Define functional requirements\n"
            "- Define non-functional constraints\n"
            "- Capture acceptance criteria\n"
        ),
        "architecture.md": (
            "# Architecture\n\n"
            "## Overview\n"
            "Describe the high-level system design.\n\n"
            "## Components\n"
            "- Component A\n"
            "- Component B\n"
        ),
        "decisions.md": (
            "# Decisions\n\n"
            "Record significant technical and product decisions here.\n"
        ),
        "milestones.md": (
            "# Milestones\n\n"
            "## Milestone 1: Project Setup\n"
            "- **Objective**: Establish the initial project structure.\n"
            "- **Scope**: Bootstrap docs, runtime state, and baseline workflows.\n"
            "- **Validation**: Confirm core commands run successfully.\n"
            "- **Forge Actions**:\n"
            "  - append_section requirements Overview | FORGE_INIT_MARKER\n"
            "  - mark_milestone_completed\n"
            "- **Forge Validation**:\n"
            "  - file_contains requirements FORGE_INIT_MARKER\n"
        ),
    }

