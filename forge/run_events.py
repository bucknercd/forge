"""
Structured run events for user-facing progress (not logging).

Emitters call RunEventBus.emit(); handlers render to CLI, JSONL, etc.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

# Core event types (stable string IDs for logs and renderers)
RUN_STARTED = "run_started"
PHASE_STARTED = "phase_started"
PHASE_COMPLETED = "phase_completed"
ARTIFACT_WRITTEN = "artifact_written"
PLAN_SAVED = "plan_saved"
ACTION_APPLIED = "action_applied"
VALIDATION_STARTED = "validation_started"
VALIDATION_COMPLETED = "validation_completed"
RUN_COMPLETED = "run_completed"
RUN_FAILED = "run_failed"

RunEventHandler = Callable[[dict[str, Any]], None]


@dataclass
class RunEventBus:
    """Dispatches structured events to zero or more handlers."""

    run_id: str
    handlers: list[RunEventHandler] = field(default_factory=list)

    def add_handler(self, handler: RunEventHandler) -> None:
        self.handlers.append(handler)

    def emit(self, event_type: str, /, **data: Any) -> None:
        record: dict[str, Any] = {
            "type": event_type,
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "data": dict(data),
        }
        for handler in self.handlers:
            handler(record)


class NullRunEventBus:
    """No-op emitter for optional integration."""

    run_id: str = ""

    def emit(self, event_type: str, /, **data: Any) -> None:
        return None

    def add_handler(self, handler: RunEventHandler) -> None:
        return None


def as_emitter(bus: RunEventBus | NullRunEventBus | None) -> RunEventBus | NullRunEventBus:
    return bus if bus is not None else NullRunEventBus()
