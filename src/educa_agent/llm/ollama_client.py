"""Локальные модели через Ollama: бесплатно, без интернета, данные не покидают компьютер."""

from __future__ import annotations

from typing import Any

import ollama
from loguru import logger
from pydantic import BaseModel

from educa_agent.config import LLMRole, OllamaSettings
from educa_agent.llm.base import LLMError, LLMTruncated

INSTALL_HINT = "установи Ollama с https://ollama.com/download и запусти её"


class OllamaClient:
    provider = "ollama"

    def __init__(self, settings: OllamaSettings, client: ollama.Client | None = None):
        self.settings = settings
        self._client = client

    @property
    def raw(self) -> ollama.Client:
        if self._client is None:
            self._client = ollama.Client(host=self.settings.host, timeout=self.settings.timeout_s)
        return self._client

    def model_for(self, role: LLMRole) -> str:
        return self.settings.model_for(role)

    def installed_models(self) -> list[str]:
        """Скачанные модели. Бросает LLMError, если Ollama не запущена."""
        try:
            return sorted(m.model for m in self.raw.list().models if m.model)
        except ConnectionError as e:
            raise LLMError(f"Ollama не отвечает — {INSTALL_HINT}") from e

    def complete(
        self,
        *,
        role: LLMRole,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> str:
        response = self._chat(
            role, [{"role": "system", "content": system}, *messages], max_tokens
        )
        return response.message.content or ""

    def parse[T: BaseModel](
        self,
        *,
        role: LLMRole,
        system: str,
        prompt: str,
        schema: type[T],
        max_tokens: int | None = None,
    ) -> T:
        """Ollama ограничивает вывод JSON-схемой; значения проверяет Pydantic."""
        response = self._chat(
            role,
            [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            max_tokens,
            schema=schema.model_json_schema(),
        )
        return schema.model_validate_json(response.message.content or "")

    def _chat(
        self,
        role: LLMRole,
        messages: list[dict[str, Any]],
        max_tokens: int | None,
        schema: dict[str, Any] | None = None,
    ) -> ollama.ChatResponse:
        model = self.model_for(role)
        try:
            response = self.raw.chat(
                model=model,
                messages=messages,
                format=schema,
                think=self.settings.think,
                keep_alive=self.settings.keep_alive,
                options={
                    "num_ctx": self.settings.num_ctx,
                    "num_predict": max_tokens or self.settings.max_tokens,
                },
            )
        except ConnectionError as e:
            raise LLMError(f"Ollama не отвечает — {INSTALL_HINT}") from e
        except ollama.ResponseError as e:
            if e.status_code == 404:
                raise LLMError(f"модель {model} не скачана — выполни: ollama pull {model}") from e
            raise LLMError(f"Ollama: {e.error}") from e

        if response.done_reason == "length":
            raise LLMTruncated("ответ обрезан по max_tokens — увеличь лимит в settings.yaml")
        logger.debug(
            "LLM {} · in={} out={} · {:.1f} c",
            model,
            response.prompt_eval_count,
            response.eval_count,
            (response.total_duration or 0) / 1e9,
        )
        return response
