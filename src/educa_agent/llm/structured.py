"""Структурированные ответы с одной попыткой исправления.

Structured outputs гарантируют валидный JSON по схеме, но часть ограничений Pydantic
(например, `ge`/`le` у Diagnosis.severity) проверяется только после ответа. Если проверка
не прошла, модель получает текст ошибки и отвечает заново.
"""

from loguru import logger
from pydantic import BaseModel, ValidationError

from educa_agent.config import LLMRole
from educa_agent.llm.base import LLMBackend, LLMError


def ask_structured[T: BaseModel](
    llm: LLMBackend,
    schema: type[T],
    *,
    role: LLMRole,
    system: str,
    prompt: str,
    retries: int = 1,
) -> T:
    attempt_prompt = prompt
    for attempt in range(retries + 1):
        try:
            return llm.parse(role=role, system=system, prompt=attempt_prompt, schema=schema)
        except ValidationError as e:
            logger.warning(
                "Ответ не прошёл схему {} (попытка {}): {}", schema.__name__, attempt + 1, e
            )
            attempt_prompt = (
                f"{prompt}\n\nПрошлый ответ не прошёл проверку схемы:\n{e}\n"
                "Исправь значения и ответь заново."
            )
    raise LLMError(f"ответ не соответствует схеме {schema.__name__} после {retries + 1} попыток")
