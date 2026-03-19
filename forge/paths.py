# forge/paths.py

from pathlib import Path

class Paths:
    BASE_DIR = Path.cwd()
    DOCS_DIR = BASE_DIR / "docs"
    SYSTEM_DIR = BASE_DIR / ".system"
    VISION_FILE = DOCS_DIR / "vision.txt"
    REQUIREMENTS_FILE = DOCS_DIR / "requirements.md"
    ARCHITECTURE_FILE = DOCS_DIR / "architecture.md"
    DECISIONS_FILE = DOCS_DIR / "decisions.md"
    MILESTONES_FILE = DOCS_DIR / "milestones.md"
    RUN_HISTORY_FILE = SYSTEM_DIR / "run_history.log"