# forge/paths.py

from pathlib import Path

class Paths:
    BASE_DIR = Path.cwd()
    DOCS_DIR = BASE_DIR / "docs"
    SYSTEM_DIR = BASE_DIR / ".system"
    ARTIFACTS_DIR = BASE_DIR / "artifacts"
    VISION_FILE = DOCS_DIR / "vision.txt"
    REQUIREMENTS_FILE = DOCS_DIR / "requirements.md"
    ARCHITECTURE_FILE = DOCS_DIR / "architecture.md"
    DECISIONS_FILE = DOCS_DIR / "decisions.md"
    MILESTONES_FILE = DOCS_DIR / "milestones.md"
    RUN_HISTORY_FILE = SYSTEM_DIR / "run_history.log"

    @classmethod
    def refresh(cls, base_dir: Path | None = None) -> None:
        """
        Recompute all project paths from a target project root.
        Defaults to current working directory for standalone CLI mode.
        """
        root = base_dir or Path.cwd()
        cls.BASE_DIR = root
        cls.DOCS_DIR = root / "docs"
        cls.SYSTEM_DIR = root / ".system"
        cls.ARTIFACTS_DIR = root / "artifacts"
        cls.VISION_FILE = cls.DOCS_DIR / "vision.txt"
        cls.REQUIREMENTS_FILE = cls.DOCS_DIR / "requirements.md"
        cls.ARCHITECTURE_FILE = cls.DOCS_DIR / "architecture.md"
        cls.DECISIONS_FILE = cls.DOCS_DIR / "decisions.md"
        cls.MILESTONES_FILE = cls.DOCS_DIR / "milestones.md"
        cls.RUN_HISTORY_FILE = cls.SYSTEM_DIR / "run_history.log"

    @classmethod
    def ensure_project_structure(cls) -> None:
        """Ensure base Forge directories exist for the current target project."""
        cls.DOCS_DIR.mkdir(parents=True, exist_ok=True)
        cls.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
        cls.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)