from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ProviderResult:
    data: dict[str, Any] | str
    provider: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    retry_count: int = 0
    json_repair_used: bool = False


class ModelProvider(ABC):
    name: str
    model: str

    @property
    def image_model(self) -> str:
        return self.model

    @abstractmethod
    def complete_json(
        self,
        *,
        agent: str,
        instructions: str,
        payload: dict[str, Any],
        schema_hint: dict[str, Any],
    ) -> ProviderResult:
        raise NotImplementedError

    def complete_json_with_images(
        self,
        *,
        agent: str,
        instructions: str,
        payload: dict[str, Any],
        image_paths: list[Path],
        schema_hint: dict[str, Any],
    ) -> ProviderResult:
        """Multimodal hook. Providers may override; text-only providers receive image metadata."""
        enriched = dict(payload)
        enriched["image_files"] = [path.name for path in image_paths]
        return self.complete_json(
            agent=agent, instructions=instructions, payload=enriched, schema_hint=schema_hint
        )

    @abstractmethod
    def complete_text(
        self, *, agent: str, instructions: str, payload: dict[str, Any]
    ) -> ProviderResult:
        raise NotImplementedError
