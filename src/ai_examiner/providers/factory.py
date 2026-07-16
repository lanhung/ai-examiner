from __future__ import annotations

import json
import urllib.error
import urllib.request

from ..config import Settings
from .base import ModelProvider
from .mock import MockProvider

SUPPORTED_PROVIDERS = {"mock", "openai", "anthropic", "gemini", "ollama", "qwen"}


def parse_profile(profile: str) -> tuple[str, str]:
    if ":" not in profile:
        raise ValueError("Model profile must use provider:model format")
    provider, model = profile.split(":", 1)
    if provider not in SUPPORTED_PROVIDERS or not model:
        raise ValueError(f"Unsupported model profile: {profile}")
    return provider, model


def _ollama_model_ready(base_url: str, model: str) -> bool:
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=1.0) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False
    models = data.get("models") or []
    names = {item.get("name") for item in models if isinstance(item, dict)}
    return model in names


def profile_ready(settings: Settings, profile: str) -> bool:
    provider, model = parse_profile(profile)
    if provider == "mock":
        return True
    if provider == "ollama":
        return _ollama_model_ready(settings.ollama_base_url, model)
    return bool(settings.api_key_for(provider))


def build_provider(settings: Settings, profile: str | None = None) -> ModelProvider:
    if profile:
        provider_name, model = parse_profile(profile)
    else:
        provider_name = settings.model_provider
        model = settings.default_model_for(provider_name)

    if provider_name == "mock":
        return MockProvider()

    if provider_name == "ollama":
        from .ollama_provider import OllamaProvider

        return OllamaProvider(
            settings.ollama_base_url,
            model,
            timeout=settings.ollama_request_timeout_seconds,
            document_char_limit=settings.ollama_document_chars,
            num_ctx=settings.ollama_num_ctx,
            num_predict=settings.ollama_num_predict,
        )

    api_key = settings.api_key_for(provider_name)
    if not api_key:
        raise RuntimeError(f"{provider_name} provider requires its API key in .env")

    if provider_name == "openai":
        from .openai_provider import OpenAIProvider

        return OpenAIProvider(api_key, model)
    if provider_name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key, model)
    if provider_name == "gemini":
        from .gemini_provider import GeminiProvider

        return GeminiProvider(api_key, model)
    if provider_name == "qwen":
        from .qwen_provider import QwenProvider

        return QwenProvider(
            api_key,
            model,
            base_url=settings.dashscope_base_url,
            visual_model=settings.qwen_visual_model,
            timeout=settings.qwen_request_timeout_seconds,
        )
    raise RuntimeError(f"Unsupported provider: {provider_name}")
