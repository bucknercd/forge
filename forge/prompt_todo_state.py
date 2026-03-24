"""
Deprecated compatibility shim.

Task-first implementation now lives in ``forge.prompt_task_state``.
Keep this module only to preserve old imports during migration.
"""

from __future__ import annotations

from forge.prompt_task_state import *  # noqa: F403
