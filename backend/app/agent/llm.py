"""LLM boundary. FakeLLM is deterministic (tests/CI); AnthropicLLM is used in real runs."""
from __future__ import annotations

from typing import Any, Protocol

from app.agent.schemas import ActionProposal


class LLM(Protocol):
    async def classify(self, message: str) -> str: ...
    async def draft(self, message: str, context: dict) -> ActionProposal | None: ...  # type: ignore[type-arg]
    async def reply(self, message: str, outcome: str) -> str: ...


def make_llm(settings: Any) -> LLM:
    if settings.llm_provider == "anthropic":
        from pathlib import Path

        from anthropic import AsyncAnthropic

        from app.agent.anthropic_llm import AnthropicLLM, FixtureStore

        fixtures = FixtureStore(Path(settings.llm_fixture_dir), settings.llm_fixture_mode)
        return AnthropicLLM(AsyncAnthropic(), settings.llm_model, fixtures)  # type: ignore[arg-type]
    from app.agent.fake_llm import FakeLLM

    return FakeLLM()
