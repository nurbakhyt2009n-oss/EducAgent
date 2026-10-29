"""Claude через Anthropic SDK: выбор модели по роли, prompt caching, бюджет, отказы.

Ретраи (429, 5xx, сеть) делает сам SDK — `max_retries` из settings.yaml.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import anthropic
from loguru import logger
from pydantic import BaseModel

from educa_agent.config import AnthropicSettings, LLMRole, ModelPrice
from educa_agent.llm.base import BudgetExceeded, LLMError, LLMRefusal, LLMTruncated

# Серверный fallback при отказе: API сам выбирает запасную модель по категории отказа.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class CostTracker:
    """Считает расходы по `usage` каждого ответа и останавливает работу у потолка."""

    prices: dict[str, ModelPrice]
    limit_usd: float
    spent_usd: float = 0.0
    calls: int = 0
    by_model: dict[str, float] = field(default_factory=dict)

    def check(self) -> None:
        if self.spent_usd >= self.limit_usd:
            raise BudgetExceeded(
                f"бюджет сессии исчерпан: ${self.spent_usd:.4f} из ${self.limit_usd:.2f}"
            )

    def record(self, model: str, usage: Any) -> float:
        price = self.prices.get(model)
        if price is None:
            logger.warning("Нет цены для модели {}, расход не учтён", model)
            return 0.0
        cost = (
            usage.input_tokens * price.input
            + usage.output_tokens * price.output
            + (getattr(usage, "cache_creation_input_tokens", None) or 0) * price.cache_write
            + (getattr(usage, "cache_read_input_tokens", None) or 0) * price.cache_read
        ) / 1_000_000
        self.spent_usd += cost
        self.calls += 1
        self.by_model[model] = self.by_model.get(model, 0.0) + cost
        return cost


class AnthropicClient:
    provider = "anthropic"

    def __init__(self, settings: AnthropicSettings, client: anthropic.Anthropic | None = None):
        self.settings = settings
        self.costs = CostTracker(settings.prices, settings.budget_usd_per_session)
        self._client = client

    @property
    def raw(self) -> anthropic.Anthropic:
        """SDK-клиент создаётся при первом запросе: `educa --help` работает без ключа."""
        if self._client is None:
            self._client = anthropic.Anthropic(
                timeout=self.settings.timeout_s,
                max_retries=self.settings.max_retries,
            )
        return self._client

    def model_for(self, role: LLMRole) -> str:
        return self.settings.model_for(role)

    def complete(
        self,
        *,
        role: LLMRole,
        system: str,
        messages: list[dict[str, Any]],
        max_tokens: int | None = None,
    ) -> str:
        """Системный промпт кешируется: он одинаков во всех репликах блока."""
        self.costs.check()
        model = self.model_for(role)
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens or self.settings.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": messages,
            "output_config": {"effort": self.settings.effort[role]},
        }
        if model in self.settings.refusal_fallback_models:
            response = self.raw.beta.messages.create(
                **params, betas=[FALLBACK_BETA], fallbacks="default"
            )
        else:
            response = self.raw.messages.create(**params)

        self._account(model, response)
        self._raise_for_stop(response)
        return "".join(b.text for b in response.content if b.type == "text")

    def parse[T: BaseModel](
        self,
        *,
        role: LLMRole,
        system: str,
        prompt: str,
        schema: type[T],
        max_tokens: int | None = None,
    ) -> T:
        """Structured outputs: SDK проверяет ответ по Pydantic-схеме."""
        self.costs.check()
        model = self.model_for(role)
        response = self.raw.messages.parse(
            model=model,
            max_tokens=max_tokens or self.settings.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": prompt}],
            output_format=schema,
        )
        self._account(model, response)
        self._raise_for_stop(response)
        if response.parsed_output is None:
            raise LLMError("модель не вернула структурированный ответ")
        return response.parsed_output

    def _account(self, requested_model: str, response: Any) -> None:
        # При fallback ответ мог прийти от другой модели — считаем по её цене.
        model = getattr(response, "model", None) or requested_model
        if model not in self.settings.prices:
            model = requested_model
        cost = self.costs.record(model, response.usage)
        logger.debug(
            "LLM {} · in={} out={} cache_read={} · ${:.5f} · id={}",
            model,
            response.usage.input_tokens,
            response.usage.output_tokens,
            getattr(response.usage, "cache_read_input_tokens", None) or 0,
            cost,
            getattr(response, "_request_id", None),
        )

    @staticmethod
    def _raise_for_stop(response: Any) -> None:
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise LLMRefusal(
                getattr(details, "category", None), getattr(details, "explanation", None)
            )
        if response.stop_reason == "max_tokens":
            raise LLMTruncated("ответ обрезан по max_tokens — увеличь лимит")
