from pydantic import BaseModel, Field

from shared.llm.client import LLMClient


class NarrativeResponse(BaseModel):
    explanation: str = Field(default="")
    risks: list[str] = Field(default_factory=list)


def test_llm_fallback_preserves_model_defaults():
    """An unavailable LLM must return a complete safe response object."""
    client = LLMClient(provider="gemini", api_key="")

    result = client._generate_fallback(NarrativeResponse, "untrusted job content")

    assert result.explanation == ""
    assert result.risks == []
