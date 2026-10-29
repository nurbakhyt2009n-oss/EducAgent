"""Выбор поставщика модели по `llm.provider` из settings.yaml."""

from educa_agent.config import LLMSettings
from educa_agent.llm.base import LLMBackend


def make_llm(settings: LLMSettings) -> LLMBackend:
    # Импорты внутри: SDK неактивного поставщика не загружается.
    if settings.provider == "ollama":
        from educa_agent.llm.ollama_client import OllamaClient

        return OllamaClient(settings.ollama)

    from educa_agent.llm.anthropic_client import AnthropicClient

    return AnthropicClient(settings.anthropic)
