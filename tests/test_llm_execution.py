import json

from forge.design_manager import Milestone
from forge.executor import Executor
from forge.paths import Paths
from forge.llm import LLMClient


class FakeLLMClient(LLMClient):
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.outputs:
            return ""
        return self.outputs.pop(0)


def _write_simple_milestones(path):
    path.write_text(
        """
# Milestones

## Milestone 1: LLM
- **Objective**: Do work
- **Scope**: Some scope
- **Validation**: Validate result fields
"""
    )


def test_execute_milestone_uses_llm_output_for_summary(tmp_path):
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    _write_simple_milestones(Paths.MILESTONES_FILE)
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    fake = FakeLLMClient([json.dumps({"summary": "LLM proposed output"})])
    Executor.execute_milestone(1, llm_client=fake)

    state = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert state["1"]["status"] == "completed"
    assert state["1"]["attempts"] == 1

    result = json.loads((Paths.SYSTEM_DIR / "results" / "milestone_1.json").read_text())
    assert result["summary"] == "LLM proposed output"
    assert "llm_output" in result


def test_retry_prompt_includes_validation_failure_when_llm_output_invalid(tmp_path):
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    _write_simple_milestones(Paths.MILESTONES_FILE)
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    # First attempt: invalid output (no summary field), should fail validation.
    # Second attempt: valid JSON, should succeed.
    fake = FakeLLMClient([json.dumps({}), json.dumps({"summary": "Fixed output"})])
    Executor.execute_milestone(1, llm_client=fake)

    state1 = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert state1["1"]["status"] == "retry_pending"
    assert state1["1"]["attempts"] == 1

    # Check prompt 1 was the base prompt.
    assert "This is a retry" not in fake.prompts[0]

    Executor.execute_milestone(1, llm_client=fake)
    state2 = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert state2["1"]["status"] == "completed"
    assert state2["1"]["attempts"] == 2

    # Second call should use a retry prompt containing the validator reason.
    assert "This is a retry for the given milestone." in fake.prompts[1]
    assert "Result missing required fields" in fake.prompts[1]


def test_execute_milestone_handles_empty_llm_output(tmp_path):
    Paths.MILESTONES_FILE = tmp_path / "milestones.md"
    _write_simple_milestones(Paths.MILESTONES_FILE)
    Paths.SYSTEM_DIR = tmp_path / ".system"
    Paths.SYSTEM_DIR.mkdir()

    fake = FakeLLMClient(["", json.dumps({"summary": "Second try"})])
    Executor.execute_milestone(1, llm_client=fake)

    state1 = json.loads((Paths.SYSTEM_DIR / "milestone_state.json").read_text())
    assert state1["1"]["status"] == "retry_pending"
    assert state1["1"]["attempts"] == 1

