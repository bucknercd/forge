import json
from pathlib import Path

from forge.design_manager import MilestoneService
from forge.paths import Paths
from forge.milestone_state import normalize_milestone_state_value


DEFAULT_ENTRY = {"status": "not_started", "attempts": 0}


def sync_milestone_state() -> dict:
    """
    Reconcile milestone_state.json with currently parsed milestones.

    Returns a summary with:
    - initialized: whether the state file was created from missing
    - added: list of milestone ids added to state
    - removed: list of stale milestone ids removed from state
    - unchanged: whether no add/remove changes were needed
    """
    Paths.ensure_project_structure()
    state_file = Paths.SYSTEM_DIR / "milestone_state.json"
    milestones = MilestoneService.list_milestones()
    expected_ids = {str(milestone.id) for milestone in milestones}

    initialized = not state_file.exists()
    if initialized:
        current_state = {}
    else:
        with state_file.open("r", encoding="utf-8") as file:
            current_state = json.load(file)

    # Normalize any legacy/non-uniform entries in the existing state file.
    for k in list(current_state.keys()):
        current_state[k] = normalize_milestone_state_value(current_state[k])

    added = []
    for milestone_id in sorted(expected_ids, key=int):
        if milestone_id not in current_state:
            current_state[milestone_id] = dict(DEFAULT_ENTRY)
            added.append(milestone_id)

    stale_ids = [mid for mid in current_state.keys() if mid not in expected_ids]
    removed = sorted(stale_ids, key=int) if stale_ids else []
    for milestone_id in removed:
        del current_state[milestone_id]

    with state_file.open("w", encoding="utf-8") as file:
        json.dump(current_state, file, indent=4)

    return {
        "initialized": initialized,
        "added": added,
        "removed": removed,
        "unchanged": not added and not removed,
    }
