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
    def log_milestone_attempt(
        milestone_id: int,
        milestone_title: str,
        status: str,
        error_message: str | None = None,
        artifact_summary: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        """
        Append one structured milestone attempt entry as JSONL.
        status should be one of: "success", "failure".
        """
        Paths.SYSTEM_DIR.mkdir(parents=True, exist_ok=True)
        if not Paths.RUN_HISTORY_FILE.exists():
            Paths.RUN_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            Paths.RUN_HISTORY_FILE.touch()

        ts = (timestamp or datetime.now()).isoformat()
        log_entry = {
            "ts": ts,
            "milestone_id": milestone_id,
            "milestone_title": milestone_title,
            "status": status,
        }
        if error_message:
            log_entry["error_message"] = error_message
        if artifact_summary:
            log_entry["artifact_summary"] = artifact_summary

        FileRepository.append_to_file(Paths.RUN_HISTORY_FILE, json.dumps(log_entry))

    @staticmethod
    def get_recent_entries(limit: int = 5) -> list[dict]:
        # Ensure the run_history.log file exists
        if not Paths.RUN_HISTORY_FILE.exists():
            return []

        with Paths.RUN_HISTORY_FILE.open("r", encoding="utf-8") as file:
            lines = file.readlines()
        return [json.loads(line) for line in lines[-limit:]]