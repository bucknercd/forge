from forge.design_manager import Milestone


FORGE_CONSTRAINTS = [
    "Python standard library only",
    "file-based persistence only",
    "no frameworks",
    "keep implementation minimal",
]


def build_execution_prompt(milestone: Milestone, attempt: int) -> str:
    constraints_text = "\n".join(f"- {c}" for c in FORGE_CONSTRAINTS)
    return (
        "You are Forge. Produce an implementation proposal for the given milestone.\n"
        f"Milestone ID: {milestone.id}\n"
        f"Title: {milestone.title}\n"
        f"Attempt: {attempt}\n"
        f"Objective: {milestone.objective}\n"
        f"Scope: {milestone.scope}\n"
        f"Validation: {milestone.validation}\n"
        + (
            f"Summary: {milestone.summary}\n\n"
            if (milestone.summary or "").strip()
            else "\n"
        )
        + "Forge constraints:\n"
        f"{constraints_text}\n\n"
        "Return ONLY valid JSON with at least: {\"summary\": \"...\"}."
    )


def build_retry_prompt(
    milestone: Milestone,
    attempt: int,
    failure_summary: str,
) -> str:
    constraints_text = "\n".join(f"- {c}" for c in FORGE_CONSTRAINTS)
    failure_summary = failure_summary.strip() if failure_summary else ""
    failure_section = (
        f"Previous validation failure:\n{failure_summary}\n\n"
        if failure_summary
        else "Previous validation failure: <none captured>\n\n"
    )
    return (
        "You are Forge. This is a retry for the given milestone.\n"
        f"Milestone ID: {milestone.id}\n"
        f"Title: {milestone.title}\n"
        f"Attempt: {attempt}\n"
        f"Objective: {milestone.objective}\n"
        f"Scope: {milestone.scope}\n"
        f"Validation: {milestone.validation}\n"
        + (
            f"Summary: {milestone.summary}\n\n"
            if (milestone.summary or "").strip()
            else "\n"
        )
        + f"{failure_section}"
        "Fix only what is necessary to satisfy the validation rules.\n"
        "Return ONLY valid JSON with at least: {\"summary\": \"...\"}."
    )

