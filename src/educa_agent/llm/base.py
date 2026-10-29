"""Общий интерфейс LLM. Остальной код зависит только от него, а не от поставщика модели."""

from typing import Any, Protocol

from pydantic import BaseModel

from educa_agent.config import LLMRole


class LLMError(RuntimeError):
    pass


class LLMRefusal(LLMError):
    def __init__(self, category: str | None, explanation: str | None):
        super().__init__(f"модель отказалась отвечать (категория: {category or 'не указана'})")
        self.category = category
        self.explanation = explanation


class LLMTruncated(LLMError):
    pass


class BudgetExceeded(LLMError):
    pass


class LLMBackend(Protocol):
    provider: str

    def model_for(self, role: LLMRole) -> str: ...

    def complete(
        self,
        *,
        role: LLMRole,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> str:
        """Текстовый ответ на диалог `messages` (роли user / assistant)."""
        ...

    def parse[T: BaseModel](
        self,
        *,
        role: LLMRole,
        system: str,
        prompt: str,
        schema: type[T],
        max_tokens: int | None = None,
    ) -> T:
        """Ответ строго по Pydantic-схеме. Невалидный ответ — pydantic.ValidationError."""
        ...
