# forge/models.py

from dataclasses import dataclass
from datetime import datetime

@dataclass
class Decision:
    title: str
    context: str
    decision: str
    rationale: str
    timestamp: datetime

@dataclass
class RunHistoryEntry:
    task: str
    summary: str
    status: str
    timestamp: datetime