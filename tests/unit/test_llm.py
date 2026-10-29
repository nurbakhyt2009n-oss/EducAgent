"""LLM-клиенты на поддельных SDK: без сети, без Ollama и без расходов."""

from types import SimpleNamespace

import ollama
import pytest
from jinja2 import UndefinedError
from pydantic import BaseModel, ValidationError

from educa_agent.config import LLMSettings
from educa_agent.llm.anthropic_client import FALLBACK_BETA, AnthropicClient
from educa_agent.llm.base import BudgetExceeded, LLMError, LLMRefusal, LLMTruncated
from educa_agent.llm.client import make_llm
from educa_agent.llm.ollama_client import OllamaClient
from educa_agent.llm.prompts import PromptRenderer
from educa_agent.llm.structured import ask_structured


class Verdict(BaseModel):
    met: bool


def _validation_error() -> ValidationError:
    try:
        Verdict.model_validate({"met": "может быть"})
    except ValidationError as err:
        return err
    raise AssertionError("ожидалась ошибка валидации")


# ---------- выбор поставщика ----------

def test_default_provider_is_free_ollama(config):
    assert config.app.llm.provider == "ollama"
    assert isinstance(make_llm(config.app.llm), OllamaClient)


def test_anthropic_provider_selectable(config):
    settings = LLMSettings.model_validate(
        config.app.llm.model_dump() | {"provider": "anthropic"}
    )
    assert isinstance(make_llm(settings), AnthropicClient)


# ---------- Ollama ----------

class FakeOllama:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def list(self):
        return SimpleNamespace(models=[SimpleNamespace(model="qwen3:4b")])


def _ollama_response(content="Ответ", done_reason="stop"):
    return SimpleNamespace(
        message=SimpleNamespace(content=content),
        done_reason=done_reason,
        prompt_eval_count=10,
        eval_count=5,
        total_duration=1_000_000_000,
    )


def _ollama(config, *results):
    fake = FakeOllama(*results)
    return OllamaClient(config.app.llm.ollama, client=fake), fake


def test_ollama_complete_puts_system_first(config):
    llm, fake = _ollama(config, _ollama_response("Привет"))
    answer = llm.complete(role="tutor", system="sys", messages=[{"role": "user", "content": "?"}])
    assert answer == "Привет"
    call = fake.calls[0]
    assert call["model"] == "qwen3:4b"
    assert call["messages"][0] == {"role": "system", "content": "sys"}
    assert call["options"] == {"num_ctx": 8192, "num_predict": 2048}
    assert call["think"] is False


def test_ollama_parse_sends_schema_and_validates(config):
    llm, fake = _ollama(config, _ollama_response('{"met": true}'))
    result = llm.parse(role="fast", system="s", prompt="Выполнен?", schema=Verdict)
    assert result == Verdict(met=True)
    assert fake.calls[0]["format"] == Verdict.model_json_schema()


def test_ollama_parse_invalid_json_raises_validation_error(config):
    llm, _ = _ollama(config, _ollama_response('{"met": "может быть"}'))
    with pytest.raises(ValidationError):
        llm.parse(role="fast", system="s", prompt="?", schema=Verdict)


def test_ollama_not_running_gives_install_hint(config):
    llm, _ = _ollama(config, ConnectionError("Failed to connect to Ollama"))
    with pytest.raises(LLMError, match="ollama.com/download"):
        llm.complete(role="fast", system="s", messages=[])


def test_ollama_missing_model_gives_pull_command(config):
    llm, _ = _ollama(config, ollama.ResponseError("model not found", status_code=404))
    with pytest.raises(LLMError, match="ollama pull qwen3:4b"):
        llm.complete(role="fast", system="s", messages=[])


def test_ollama_truncated_answer_raises(config):
    llm, _ = _ollama(config, _ollama_response(done_reason="length"))
    with pytest.raises(LLMTruncated):
        llm.complete(role="fast", system="s", messages=[])


def test_ollama_installed_models(config):
    llm, _ = _ollama(config)
    assert llm.installed_models() == ["qwen3:4b"]


# ---------- Anthropic ----------

def _response(text="Ответ", stop_reason="end_turn", model="claude-haiku-5-5", parsed=None):
    return SimpleNamespace(
        model=model,
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="cyber", explanation="..."),
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=text),
        ],
        usage=SimpleNamespace(
            input_tokens=1_000_000, output_tokens=100_000,
            cache_creation_input_tokens=0, cache_read_input_tokens=0,
        ),
        parsed_output=parsed,
    )


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _anthropic(config, *responses):
    messages = FakeMessages(responses)
    fake = SimpleNamespace(messages=messages, beta=SimpleNamespace(messages=messages))
    return AnthropicClient(config.app.llm.anthropic, client=fake), messages


def test_anthropic_complete_returns_text_and_counts_cost(config):
    llm, messages = _anthropic(config, _response("Привет"))
    answer = llm.complete(role="fast", system="sys", messages=[{"role": "user", "content": "?"}])
    assert answer == "Привет"
    # 1M входных × $0.10 + 100K выходных × $0.50 / 1M
    assert llm.costs.spent_usd == pytest.approx(0.15)
    call = messages.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert call["output_config"] == {"effort": "low"}
    assert "fallbacks" not in call          # у Haiku 5.5 нет серверного fallback
    assert "temperature" not in call        # параметры сэмплинга API больше не принимает


def test_anthropic_tutor_uses_refusal_fallback(config):
    llm, messages = _anthropic(config, _response(model="claude-sonnet-5-5"))
    llm.complete(role="tutor", system="sys", messages=[{"role": "user", "content": "?"}])
    call = messages.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["fallbacks"] == "default"
    assert call["betas"] == [FALLBACK_BETA]


def test_anthropic_refusal_raises(config):
    llm, _ = _anthropic(config, _response(stop_reason="refusal"))
    with pytest.raises(LLMRefusal) as e:
        llm.complete(role="fast", system="s", messages=[])
    assert e.value.category == "cyber"


def test_anthropic_truncated_answer_raises(config):
    llm, _ = _anthropic(config, _response(stop_reason="max_tokens"))
    with pytest.raises(LLMTruncated):
        llm.complete(role="fast", system="s", messages=[])


def test_anthropic_budget_stops_calls_before_request(config):
    llm, messages = _anthropic(config)
    llm.costs.spent_usd = config.app.llm.anthropic.budget_usd_per_session
    with pytest.raises(BudgetExceeded):
        llm.complete(role="fast", system="s", messages=[])
    assert messages.calls == []


# ---------- общее ----------

def test_ask_structured_retries_once_on_validation_error(config):
    llm, fake = _ollama(config, _ollama_response('{"met": "может быть"}'),
                        _ollama_response('{"met": true}'))
    result = ask_structured(llm, Verdict, role="fast", system="s", prompt="Выполнен ли дескриптор?")
    assert result == Verdict(met=True)
    assert "не прошёл проверку схемы" in fake.calls[1]["messages"][1]["content"]


def test_ask_structured_gives_up_after_retries(config):
    bad = _ollama_response('{"met": "может быть"}')
    llm, _ = _ollama(config, bad, bad)
    with pytest.raises(LLMError, match="не соответствует схеме"):
        ask_structured(llm, Verdict, role="fast", system="s", prompt="?")


def test_tutor_system_prompt_renders(config):
    renderer = PromptRenderer(config.paths.prompts)
    same = renderer.render(
        "tutor_system", subject_name="Physics", grade=10, lang="en", assessment_lang="en"
    )
    assert "Physics tutor for a grade 10 student" in same
    assert "assessment is in" not in same
    assert "{{" not in same

    mixed = renderer.render(
        "tutor_system", subject_name="Physics", grade=10, lang="en", assessment_lang="ru"
    )
    assert 'The assessment is in "ru"' in mixed


def test_missing_prompt_variable_is_an_error(config):
    with pytest.raises(UndefinedError):
        PromptRenderer(config.paths.prompts).render("tutor_system", subject_name="Physics")
