"""SQLAlchemy-модели. SQLite — источник истины: баллы, попытки, ошибки, мастерство.

Схема меняется только через миграции Alembic (memory/db/migrations).
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from educa_agent.domain.enums import AssessmentKind, ErrorType, ThinkingLevel

# Явные имена ограничений нужны Alembic, чтобы batch-миграции SQLite находили их.
NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _enum(cls: type[StrEnum]) -> Enum:
    """Храним значение enum ("conceptual"), а не имя ("CONCEPTUAL")."""
    return Enum(
        cls,
        native_enum=False,
        length=32,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map = {dict[str, Any]: JSON, list[str]: JSON}


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    path: Mapped[str] = mapped_column(String(512), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))           # pptx | pdf | objectives | past_paper
    subject: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class ChunkRow(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    location: Mapped[str] = mapped_column(String(64))       # "слайд 12" | "с. 87"
    section_path: Mapped[list[str]] = mapped_column(default=list)
    chunk_type: Mapped[str] = mapped_column(String(32))
    lang: Mapped[str] = mapped_column(String(2))
    text: Mapped[str] = mapped_column(Text)


class LearningObjectiveRow(Base):
    __tablename__ = "learning_objectives"
    __table_args__ = (UniqueConstraint("subject", "code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject: Mapped[str] = mapped_column(String(64), index=True)
    code: Mapped[str] = mapped_column(String(16))
    grade: Mapped[int] = mapped_column(Integer)
    section: Mapped[str] = mapped_column(String(256))
    quarter: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    lang: Mapped[str] = mapped_column(String(2))
    exam_weight: Mapped[float] = mapped_column(Float, default=1.0)


class ChunkLO(Base):
    __tablename__ = "chunk_lo"

    chunk_id: Mapped[str] = mapped_column(
        ForeignKey("chunks.id", ondelete="CASCADE"), primary_key=True
    )
    lo_id: Mapped[int] = mapped_column(
        ForeignKey("learning_objectives.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[float] = mapped_column(Float)


class LOPrerequisite(Base):
    """Ребро «from_lo нужен, чтобы освоить to_lo»."""

    __tablename__ = "lo_prerequisites"

    from_lo_id: Mapped[int] = mapped_column(
        ForeignKey("learning_objectives.id", ondelete="CASCADE"), primary_key=True
    )
    to_lo_id: Mapped[int] = mapped_column(
        ForeignKey("learning_objectives.id", ondelete="CASCADE"), primary_key=True
    )
    confidence: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(8))          # llm | manual


class ItemRow(Base):
    __tablename__ = "items"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    primary_lo_id: Mapped[int] = mapped_column(
        ForeignKey("learning_objectives.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[AssessmentKind] = mapped_column(_enum(AssessmentKind))
    thinking_level: Mapped[ThinkingLevel] = mapped_column(_enum(ThinkingLevel))
    difficulty_b: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(16))
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[dict[str, Any]]                         # полная модель Item
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    subject: Mapped[str] = mapped_column(String(64))
    mode: Mapped[str] = mapped_column(String(16))           # study | exam_sim
    plan: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AttemptRow(Base):
    __tablename__ = "attempts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.id"), index=True)
    item_id: Mapped[str] = mapped_column(ForeignKey("items.id"))
    lo_id: Mapped[int] = mapped_column(ForeignKey("learning_objectives.id"), index=True)
    answer: Mapped[str] = mapped_column(Text)
    hints_used: Mapped[int] = mapped_column(Integer, default=0)
    latency_s: Mapped[float] = mapped_column(Float)
    points: Mapped[float | None] = mapped_column(Float)
    max_points: Mapped[int] = mapped_column(Integer)
    grader: Mapped[str | None] = mapped_column(String(16))
    grade: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    disputed: Mapped[bool] = mapped_column(Boolean, default=False)
    exam: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )


class MisconceptionRow(Base):
    __tablename__ = "misconceptions"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    lo_id: Mapped[int] = mapped_column(ForeignKey("learning_objectives.id"), index=True)
    label: Mapped[str] = mapped_column(String(256))
    occurrences: Mapped[int] = mapped_column(Integer, default=0)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MistakeRow(Base):
    __tablename__ = "mistakes"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(ForeignKey("attempts.id"), index=True)
    lo_id: Mapped[int] = mapped_column(ForeignKey("learning_objectives.id"), index=True)
    error_type: Mapped[ErrorType] = mapped_column(_enum(ErrorType))
    severity: Mapped[float] = mapped_column(Float)
    thinking_level: Mapped[ThinkingLevel | None] = mapped_column(_enum(ThinkingLevel))
    misconception_id: Mapped[str | None] = mapped_column(ForeignKey("misconceptions.id"))
    text: Mapped[str] = mapped_column(Text)
    exam: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    # Outbox: True, пока ошибка не записана в ChromaDB. Дописывается при следующем запуске.
    pending_index: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class MasteryRow(Base):
    """Кеш θ и FSRS по LO. Всегда восстановим из журнала attempts."""

    __tablename__ = "mastery"

    lo_id: Mapped[int] = mapped_column(
        ForeignKey("learning_objectives.id", ondelete="CASCADE"), primary_key=True
    )
    theta: Mapped[float] = mapped_column(Float, default=0.0)
    attempts_count: Mapped[int] = mapped_column(Integer, default=0)
    fsrs_card: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
