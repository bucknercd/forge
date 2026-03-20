# forge/paths.py

from pathlib import Path
from forge.project_templates import starter_templates

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

    @classmethod
    def required_directories(cls) -> list[Path]:
        return [cls.DOCS_DIR, cls.SYSTEM_DIR, cls.ARTIFACTS_DIR]

    @classmethod
    def required_files(cls) -> list[Path]:
        return [
            cls.VISION_FILE,
            cls.REQUIREMENTS_FILE,
            cls.ARCHITECTURE_FILE,
            cls.DECISIONS_FILE,
            cls.MILESTONES_FILE,
            cls.RUN_HISTORY_FILE,
        ]

    @classmethod
    def initialize_project(cls) -> dict:
        """
        Initialize the current working directory as a Forge project.
        Creates required directories/files if missing and never overwrites
        existing files.
        """
        created_dirs: list[Path] = []
        created_files: list[Path] = []
        templates = starter_templates()

        for directory in cls.required_directories():
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                created_dirs.append(directory)

        for file_path in cls.required_files():
            if not file_path.exists():
                file_path.parent.mkdir(parents=True, exist_ok=True)
                template = templates.get(file_path.name)
                if template is not None:
                    file_path.write_text(template, encoding="utf-8")
                else:
                    file_path.touch()
                created_files.append(file_path)

        return {"created_dirs": created_dirs, "created_files": created_files}

    @classmethod
    def project_validation(cls) -> tuple[bool, list[Path]]:
        """
        Returns:
          (is_valid, missing_paths)
        A valid Forge project has all required directories and baseline files.
        """
        missing: list[Path] = []
        for directory in cls.required_directories():
            if not directory.exists():
                missing.append(directory)
        for file_path in cls.required_files():
            if not file_path.exists():
                missing.append(file_path)
        return len(missing) == 0, missing