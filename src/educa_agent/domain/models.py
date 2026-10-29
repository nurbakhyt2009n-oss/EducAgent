from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from educa_agent.domain.enums import AssessmentKind, ErrorType, ThinkingLevel

Lang = Literal["ru", "kk", "en"]


class LearningObjective(BaseModel):
    code: str                        # "10.2.1.3"
    subject: str
    grade: int
    section: str
    quarter: int | None = None
    text: str
    lang: Lang = "ru"
    exam_weight: float = 1.0


# "theory" — обычное объяснение, которое не подходит под остальные типы.
ChunkType = Literal["definition", "law", "theory", "worked_example",
                    "exercise", "figure", "summary"]


class Chunk(BaseModel):
    id: str
    source_id: str
    text: str
    chunk_type: ChunkType
    location: str                    # "slide 12" | "p. 87"
    section_path: list[str] = []
    lo_codes: list[str] = []


class Descriptor(BaseModel):
    id: str
    text: str                        # «записывает формулу времени подъёма»
    points: int


class Item(BaseModel):
    id: str
    lo_codes: list[str]
    kind: AssessmentKind
    thinking_level: ThinkingLevel
    difficulty_b: float = 0.0
    stem: str
    answer_type: Literal["mcq", "numeric", "expression", "short", "extended"]
    options: list[str] | None = None
    reference_answer: str
    reference_solution: str
    descriptors: list[Descriptor]
    max_points: int
    targets_misconception: str | None = None
    source: Literal["generated", "past_paper", "manual"] = "generated"
    grounding_chunk_ids: list[str] = []


class DescriptorVerdict(BaseModel):
    descriptor_id: str
    met: bool
    points: int
    evidence: str                    # цитата из ответа ученика
    missing: str | None = None


class GradeResult(BaseModel):
    points: float
    max_points: int
    verdicts: list[DescriptorVerdict]
    grader: Literal["deterministic", "symbolic", "rubric_llm"]
    agreement: float = 1.0           # согласие двух проходов оценщика


class Diagnosis(BaseModel):
    error_type: ErrorType
    severity: float = Field(ge=0, le=1)
    misconception_text: str
    misconception_id: str | None = None
    confidence: float = Field(ge=0, le=1)


class Attempt(BaseModel):
    id: str
    session_id: str
    item_id: str
    lo_code: str
    answer: str
    hints_used: int = 0
    latency_s: float
    grade: GradeResult | None = None
    diagnosis: Diagnosis | None = None
    disputed: bool = False
    exam: bool = False
    created_at: datetime


class Mistake(BaseModel):
    """Ошибка ученика: факт пишется в SQLite, текст с диагнозом — в ChromaDB."""

    id: str
    attempt_id: str
    session_id: str
    lo_code: str
    error_type: ErrorType
    severity: float = Field(ge=0, le=1)
    thinking_level: ThinkingLevel | None = None
    misconception_id: str | None = None
    text: str                        # «LO · задача · ответ ученика · диагноз»
    exam: bool = False
    resolved: bool = False
    created_at: datetime


class Misconception(BaseModel):
    """Устойчивое заблуждение — кластер повторяющихся ошибок по одному LO."""

    id: str
    lo_code: str
    label: str                       # «путает массу и вес»
    occurrences: int = 0
    last_seen: datetime | None = None
    resolved: bool = False


class LONodeState(BaseModel):
    code: str
    theta: float
    mastery: float
    retrievability: float
    error_load: float
    gap: float
    blame: float
    priority: float
    next_assessment: datetime | None = None


class PlannedBlock(BaseModel):
    lo_code: str
    reason: Literal["root_cause", "weak", "decay_review", "new", "exam_focus"]
    target_level: ThinkingLevel
    target_b: float
    misconception_ids: list[str] = []
    minutes: int


class SessionPlan(BaseModel):
    session_id: str
    mode: Literal["study", "exam_sim"]
    blocks: list[PlannedBlock]
