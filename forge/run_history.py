# forge/run_history.py

from datetime import datetime
from forge.paths import Paths
from forge.repository import FileRepository
from forge.models import RunHistoryEntry
import json

class RunHistory:
    @staticmethod
    def log_run(entry: RunHistoryEntry) -> None:
        # Ensure the .system directory exists
        Paths.SYSTEM_DIR.mkdir(exist_ok=True)

        # Ensure the run_history.log file exists
        if not Paths.RUN_HISTORY_FILE.exists():
            Paths.RUN_HISTORY_FILE.touch()

        log_entry = {
            "ts": entry.timestamp.isoformat(),
            "task": entry.task,
            "status": entry.status,
            "summary": entry.summary,
        }
        FileRepository.append_to_file(Paths.RUN_HISTORY_FILE, json.dumps(log_entry))

    @staticmethod
    def get_recent_entries(limit: int = 5) -> list[dict]:
        # Ensure the run_history.log file exists
        if not Paths.RUN_HISTORY_FILE.exists():
            return []

        with Paths.RUN_HISTORY_FILE.open("r", encoding="utf-8") as file:
            lines = file.readlines()
        return [json.loads(line) for line in lines[-limit:]]