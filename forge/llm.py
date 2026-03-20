import json


class LLMClient:
    """
    Minimal interface for an LLM-backed proposal generator.

    Implementations must be deterministic/testable under a fake client.
    """

    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class StubLLMClient(LLMClient):
    """
    Default offline stub. This keeps existing flows deterministic until
    a real provider is wired in.
    """

    def generate(self, prompt: str) -> str:
        # Keep the legacy test expectation stable.
        return json.dumps({"summary": "Execution completed successfully."})

