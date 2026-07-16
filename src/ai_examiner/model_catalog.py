from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ModelCatalogEntry:
    provider: str
    model: str
    label: str
    input_usd_per_million: float
    output_usd_per_million: float
    recommended_for: str
    supports_vision: bool = False
    pricing_as_of: str = "2026-07-10"

    @property
    def id(self) -> str:
        return f"{self.provider}:{self.model}"

    def public_dict(self, ready: bool) -> dict:
        data = asdict(self)
        data.update({"id": self.id, "ready": ready})
        return data


CATALOG: tuple[ModelCatalogEntry, ...] = (
    ModelCatalogEntry(
        provider="mock",
        model="heuristic-v2",
        label="Mock deterministic",
        input_usd_per_million=0.0,
        output_usd_per_million=0.0,
        recommended_for="offline demos and tests",
        supports_vision=True,
    ),
    ModelCatalogEntry(
        provider="openai",
        model="gpt-5.4-mini",
        label="OpenAI GPT-5.4 mini",
        input_usd_per_million=0.75,
        output_usd_per_million=4.50,
        recommended_for="balanced annotation and analysis",
        supports_vision=True,
    ),
    ModelCatalogEntry(
        provider="anthropic",
        model="claude-sonnet-5",
        label="Anthropic Claude Sonnet 5",
        input_usd_per_million=2.0,
        output_usd_per_million=10.0,
        recommended_for="deep paper review and consensus synthesis",
        supports_vision=True,
    ),
    ModelCatalogEntry(
        provider="gemini",
        model="gemini-3.5-flash",
        label="Google Gemini 3.5 Flash",
        input_usd_per_million=0.75,
        output_usd_per_million=4.50,
        recommended_for="fast multimodel annotation and benchmarking",
        supports_vision=True,
    ),
    ModelCatalogEntry(
        provider="qwen",
        model="qwen-plus",
        label="Alibaba Qwen Plus",
        input_usd_per_million=0.111,
        output_usd_per_million=0.278,
        recommended_for="Chinese text examination and structured analysis",
        pricing_as_of="2026-07-16",
    ),
    ModelCatalogEntry(
        provider="qwen",
        model="qwen3-vl-plus",
        label="Alibaba Qwen3-VL Plus",
        input_usd_per_million=0.139,
        output_usd_per_million=1.389,
        recommended_for="page, chart, table and formula review",
        supports_vision=True,
        pricing_as_of="2026-07-16",
    ),
    ModelCatalogEntry(
        provider="ollama",
        model="qwen2.5:14b",
        label="Ollama Qwen2.5 14B",
        input_usd_per_million=0.0,
        output_usd_per_million=0.0,
        recommended_for="local private analysis with stronger reasoning",
    ),
    ModelCatalogEntry(
        provider="ollama",
        model="qwen2.5:7b",
        label="Ollama Qwen2.5 7B",
        input_usd_per_million=0.0,
        output_usd_per_million=0.0,
        recommended_for="local private analysis with lower latency",
    ),
    ModelCatalogEntry(
        provider="ollama",
        model="llama3.2:3b",
        label="Ollama Llama 3.2 3B",
        input_usd_per_million=0.0,
        output_usd_per_million=0.0,
        recommended_for="local quick checks and low-cost demos",
    ),
)


def catalog_entry(provider: str, model: str) -> ModelCatalogEntry | None:
    return next((x for x in CATALOG if x.provider == provider and x.model == model), None)


def estimate_cost(provider: str, model: str, input_tokens: int, output_tokens: int) -> float:
    entry = catalog_entry(provider, model)
    if not entry:
        return 0.0
    return round(
        input_tokens * entry.input_usd_per_million / 1_000_000
        + output_tokens * entry.output_usd_per_million / 1_000_000,
        8,
    )
