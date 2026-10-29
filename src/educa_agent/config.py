"""Настройки: переменные окружения (.env) + YAML из config/.

Модели настроек строгие (`extra="forbid"`, без значений по умолчанию): опечатка или
пропущенный ключ в YAML ломает запуск сразу, а не тихо подставляет число из кода.
"""

from __future__ import annotations

import math
import os
import re
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from educa_agent.domain.enums import AssessmentKind, ErrorType, ThinkingLevel
from educa_agent.domain.models import Lang

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RAW_SUBDIRS = ("presentations", "textbooks", "objectives", "past_papers")

LLMRole = Literal["tutor", "fast"]
Effort = Literal["low", "medium", "high", "xhigh", "max"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------- settings.yaml ----------

class ModelPrice(StrictModel):
    """USD за 1 млн токенов."""

    input: float
    output: float
    cache_write: float
    cache_read: float


class _RoleModels(StrictModel):
    tutor_model: str
    fast_model: str
    max_tokens: int
    timeout_s: float

    def model_for(self, role: LLMRole) -> str:
        return self.tutor_model if role == "tutor" else self.fast_model


class OllamaSettings(_RoleModels):
    host: str
    num_ctx: int
    keep_alive: str
    think: bool


class AnthropicSettings(_RoleModels):
    effort: dict[LLMRole, Effort]
    max_retries: int
    budget_usd_per_session: float
    refusal_fallback_models: list[str]
    prices: dict[str, ModelPrice]

    @model_validator(mode="after")
    def _check_models_priced(self) -> AnthropicSettings:
        missing = {self.tutor_model, self.fast_model} - self.prices.keys()
        if missing:
            raise ValueError(f"нет цен для моделей: {sorted(missing)}")
        return self


class LLMSettings(StrictModel):
    provider: Literal["ollama", "anthropic"]
    ollama: OllamaSettings
    anthropic: AnthropicSettings

    @property
    def active(self) -> OllamaSettings | AnthropicSettings:
        return self.ollama if self.provider == "ollama" else self.anthropic


class LearnerSettings(StrictModel):
    k_initial: float
    k_stable: float
    k_switch_after: int
    k_item: float
    hint_penalty: float


class PrioritySettings(StrictModel):
    alpha: float
    beta: float
    gamma: float
    tau_days: float
    b_ref: float
    pagerank_damping: float
    foundation_gap: float
    exploration_bonus: float
    exam_weight_current_quarter: float
    exam_weight_past_quarter: float
    exam_weight_outside_soch: float


class DifficultySettings(StrictModel):
    p_target: float
    p_target_exam: float
    exam_window_days: int
    knowledge_max_b: float
    application_max_b: float


class IngestionSettings(StrictModel):
    scan_min_chars: int
    chunk_min_tokens: int
    chunk_max_tokens: int
    embed_batch_size: int
    tag_top_k: int
    tag_auto_threshold: float
    tag_llm_threshold: float
    prereq_min_confidence: float


class MemorySettings(StrictModel):
    embedding_model: str
    misconception_link_cosine: float
    misconception_window_days: int
    misconception_min_cluster: int
    misconception_resolve_streak: int
    exam_mistake_weight: float


class TutorSettings(StrictModel):
    context_chunks: int
    similar_mistakes: int
    mastery_threshold: float
    max_items_per_block: int
    max_hints: int
    max_probe_failures: int
    bank_b_tolerance: float
    bank_reuse_days: int


class EvaluationSettings(StrictModel):
    numeric_rel_tol: float
    double_check_min_points: int
    diagnosis_min_confidence: float


class AppSettings(StrictModel):
    llm: LLMSettings
    learner: LearnerSettings
    priority: PrioritySettings
    difficulty: DifficultySettings
    ingestion: IngestionSettings
    memory: MemorySettings
    tutor: TutorSettings
    evaluation: EvaluationSettings


# ---------- error_taxonomy.yaml ----------

class ErrorTypeSpec(StrictModel):
    weight: float
    description: str


class ErrorTaxonomy(StrictModel):
    types: dict[ErrorType, ErrorTypeSpec]

    @model_validator(mode="after")
    def _check_complete(self) -> ErrorTaxonomy:
        missing = set(ErrorType) - self.types.keys()
        if missing:
            raise ValueError(f"в таксономии нет типов: {sorted(missing)}")
        return self

    @property
    def weights(self) -> dict[ErrorType, float]:
        return {t: spec.weight for t, spec in self.types.items()}


# ---------- nis_assessment.yaml ----------

class ThinkingLevelSpec(StrictModel):
    label: dict[Lang, str]


class AssessmentFormat(StrictModel):
    duration_min: int
    max_points: int
    hints_allowed: bool
    level_shares: dict[ThinkingLevel, float]

    @model_validator(mode="after")
    def _check_shares(self) -> AssessmentFormat:
        total = sum(self.level_shares.values())
        if not math.isclose(total, 1.0, abs_tol=1e-6):
            raise ValueError(f"доли уровней должны давать в сумме 1, сейчас {total}")
        return self


class NisAssessment(StrictModel):
    lo_code_pattern: str
    thinking_levels: dict[ThinkingLevel, ThinkingLevelSpec]
    formats: dict[AssessmentKind, AssessmentFormat]

    @model_validator(mode="after")
    def _check_pattern(self) -> NisAssessment:
        re.compile(self.lo_code_pattern)
        return self


# ---------- subjects/*.yaml ----------

class QuarterSpec(StrictModel):
    soch_date: date | None = None
    sor_dates: list[date] = []


class SubjectConfig(StrictModel):
    id: str
    name: str
    grade: int
    lang: Lang
    assessment_lang: Lang
    quarters: dict[int, QuarterSpec]
    section_weights: dict[str, float] = {}


# ---------- окружение и пути ----------

class EnvSettings(BaseSettings):
    """Переменные окружения с префиксом EDUCA_."""

    model_config = SettingsConfigDict(env_prefix="EDUCA_", extra="ignore")

    home: Path = PROJECT_ROOT
    data_dir: Path | None = None
    config_dir: Path | None = None
    log_level: str = "INFO"


class Paths(StrictModel):
    home: Path
    config: Path
    data: Path

    @property
    def prompts(self) -> Path:
        return self.config / "prompts"

    @property
    def raw(self) -> Path:
        return self.data / "raw"

    @property
    def processed(self) -> Path:
        return self.data / "processed"

    @property
    def chroma(self) -> Path:
        return self.data / "chroma"

    @property
    def reports(self) -> Path:
        return self.data / "reports"

    @property
    def logs(self) -> Path:
        return self.data / "logs"

    @property
    def db(self) -> Path:
        return self.data / "educa.db"

    @property
    def checkpoints(self) -> Path:
        return self.data / "checkpoints.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db.as_posix()}"

    def ensure(self) -> None:
        """Создаёт папки данных, если их ещё нет."""
        for sub in RAW_SUBDIRS:
            (self.raw / sub).mkdir(parents=True, exist_ok=True)
        for path in (self.processed, self.chroma, self.reports, self.logs):
            path.mkdir(parents=True, exist_ok=True)


class Config(StrictModel):
    paths: Paths
    log_level: str
    app: AppSettings
    errors: ErrorTaxonomy
    nis: NisAssessment
    subjects: dict[str, SubjectConfig]

    def subject(self, subject_id: str) -> SubjectConfig:
        try:
            return self.subjects[subject_id]
        except KeyError:
            known = ", ".join(sorted(self.subjects)) or "нет ни одного"
            raise KeyError(
                f"предмет '{subject_id}' не найден в config/subjects (есть: {known})"
            ) from None


def _read_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(home: Path | None = None) -> Config:
    """Читает .env и все YAML. Переменные окружения важнее значений из .env."""
    home = Path(home or os.environ.get("EDUCA_HOME") or PROJECT_ROOT).resolve()
    load_dotenv(home / ".env", override=False)
    env = EnvSettings(home=home)

    config_dir = (env.config_dir or home / "config").resolve()
    data_dir = (env.data_dir or home / "data").resolve()

    subjects = {}
    for path in sorted((config_dir / "subjects").glob("*.yaml")):
        subject = SubjectConfig.model_validate(_read_yaml(path))
        if subject.id != path.stem:
            raise ValueError(f"{path.name}: id '{subject.id}' не совпадает с именем файла")
        subjects[subject.id] = subject

    return Config(
        paths=Paths(home=home, config=config_dir, data=data_dir),
        log_level=env.log_level,
        app=AppSettings.model_validate(_read_yaml(config_dir / "settings.yaml")),
        errors=ErrorTaxonomy.model_validate(_read_yaml(config_dir / "error_taxonomy.yaml")),
        nis=NisAssessment.model_validate(_read_yaml(config_dir / "nis_assessment.yaml")),
        subjects=subjects,
    )
