from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..providers.base import ModelProvider, ProviderResult

UsageCallback = Callable[[str, ProviderResult], None]


@dataclass
class AgentContext:
    provider: ModelProvider
    record_usage: UsageCallback | None = None
    prompt_overrides: dict[str, str] | None = None


class BaseAgent:
    name = "base"

    def __init__(self, context: AgentContext) -> None:
        self.context = context

    def _instructions(self, default: str) -> str:
        override = (self.context.prompt_overrides or {}).get(self.name)
        if not override:
            return default
        return f"{override}\n\nDefault safety and task constraints:\n{default}"

    def _json(
        self, instructions: str, payload: dict[str, Any], schema_hint: dict[str, Any]
    ) -> dict[str, Any]:
        result = self.context.provider.complete_json(
            agent=self.name,
            instructions=self._instructions(instructions),
            payload=payload,
            schema_hint=schema_hint,
        )
        if self.context.record_usage:
            self.context.record_usage(self.name, result)
        if not isinstance(result.data, dict):
            raise TypeError(f"{self.name} expected JSON object")
        return result.data
