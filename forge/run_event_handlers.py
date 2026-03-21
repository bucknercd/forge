"""
Handlers for RunEventBus: JSONL persistence and human CLI progress.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, TextIO

from forge.run_events import (
    ACTION_APPLIED,
    ARTIFACT_WRITTEN,
    PHASE_COMPLETED,
    PHASE_STARTED,
    PLAN_SAVED,
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_STARTED,
    VALIDATION_COMPLETED,
    VALIDATION_STARTED,
)


class JsonlRunLogHandler:
    """Append one JSON object per line (inspectable, stable)."""

    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, event: dict[str, Any]) -> None:
        line = json.dumps(event, ensure_ascii=False, sort_keys=True)
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


class EventListCollector:
    """Collect serialized events for machine-readable summaries (e.g. --json)."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(dict(event))


class CliProgressHandler:
    """
    Concise human progress; optional verbose detail.
    User-facing output only — not Python logging.
    """

    def __init__(self, *, verbose: bool = False, stream: TextIO | None = None) -> None:
        self._verbose = verbose
        self._stream = stream or sys.stdout

    def _p(self, msg: str) -> None:
        self._stream.write(msg + "\n")

    def __call__(self, event: dict[str, Any]) -> None:
        et = event.get("type", "")
        data = event.get("data") or {}

        if et == RUN_STARTED:
            cmd = data.get("command", "run")
            self._p(f"Forge run started: {cmd} (run_id={event.get('run_id', '')})")
        elif et == PHASE_STARTED:
            phase = data.get("phase", "?")
            label = data.get("label")
            extra = f" — {label}" if label else ""
            self._p(f"  → {phase}{extra}")
        elif et == PHASE_COMPLETED:
            phase = data.get("phase", "?")
            ok = data.get("ok", True)
            status = "ok" if ok else "failed"
            self._p(f"  ✓ {phase} ({status})")
            if not ok and data.get("message"):
                self._p(f"    {data['message']}")
            elif self._verbose and ok and data.get("message"):
                self._p(f"    {data['message']}")
        elif et == ARTIFACT_WRITTEN:
            path = data.get("path", "")
            kind = data.get("kind", "")
            suffix = f" [{kind}]" if kind else ""
            self._p(f"    write{suffix}: {path}")
        elif et == PLAN_SAVED:
            self._p(
                f"    plan saved: {data.get('plan_id', '')} "
                f"(milestone {data.get('milestone_id', '')})"
            )
        elif et == ACTION_APPLIED:
            at = data.get("action_type", "?")
            path = data.get("target_path") or "—"
            outcome = data.get("outcome", "?")
            self._p(f"    apply {at} [{outcome}] {path}")
            if self._verbose and data.get("error"):
                self._p(f"      error: {data['error']}")
        elif et == VALIDATION_STARTED:
            self._p(f"    validate: {data.get('name', '?')} …")
        elif et == VALIDATION_COMPLETED:
            name = data.get("name", "?")
            ok = data.get("ok", False)
            status = "pass" if ok else "fail"
            self._p(f"    validate {name}: {status}")
            if not ok and data.get("message"):
                self._p(f"      {data['message']}")
            elif self._verbose and ok and data.get("message"):
                self._p(f"      {data['message']}")
        elif et == RUN_COMPLETED:
            ok = data.get("ok", False)
            self._p(f"Overall: {'success' if ok else 'failure'}")
        elif et == RUN_FAILED:
            self._p(f"Run failed: {data.get('reason', 'unknown')}")
            if data.get("phase"):
                self._p(f"  (phase: {data['phase']})")


def write_run_meta(run_dir: Path, meta: dict[str, Any]) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    path = run_dir / "run_meta.json"
    path.write_text(
        json.dumps(meta, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
