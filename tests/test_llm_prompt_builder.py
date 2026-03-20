from forge.design_manager import Milestone
from forge.prompt_builder import build_execution_prompt, build_retry_prompt


def test_execution_prompt_includes_milestone_and_constraints():
    milestone = Milestone(
        id=1,
        title="My Milestone",
        objective="Do the thing",
        scope="Small scope",
        validation="Validation rules",
        depends_on=[],
    )
    prompt = build_execution_prompt(milestone, attempt=1)
    assert "Milestone ID: 1" in prompt
    assert "Title: My Milestone" in prompt
    assert "Objective: Do the thing" in prompt
    assert "Scope: Small scope" in prompt
    assert "Validation: Validation rules" in prompt
    assert "Python standard library only" in prompt
    assert 'Return ONLY valid JSON with at least: {"summary": "..."}.' in prompt


def test_retry_prompt_includes_failure_summary():
    milestone = Milestone(
        id=2,
        title="Retry Milestone",
        objective="Objective",
        scope="Scope",
        validation="Validation",
        depends_on=[],
    )
    prompt = build_retry_prompt(milestone, attempt=2, failure_summary="Missing summary field")
    assert "You are Forge. This is a retry for the given milestone." in prompt
    assert "Previous validation failure:" in prompt
    assert "Missing summary field" in prompt
    assert "Fix only what is necessary" in prompt
