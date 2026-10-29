"""Репозитории: единственное место, где SQL-строки превращаются в доменные модели."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from educa_agent.domain.models import Attempt, LearningObjective
from educa_agent.memory.db.tables import AttemptRow, LearningObjectiveRow, MasteryRow


class LORepo:
    def __init__(self, session: Session):
        self.s = session

    def upsert(self, lo: LearningObjective) -> int:
        """Добавляет или обновляет LO по паре (subject, code), возвращает id."""
        row = self.s.scalar(
            select(LearningObjectiveRow).filter_by(subject=lo.subject, code=lo.code)
        )
        if row is None:
            row = LearningObjectiveRow(subject=lo.subject, code=lo.code)
            self.s.add(row)
        for field in ("grade", "section", "quarter", "text", "lang", "exam_weight"):
            setattr(row, field, getattr(lo, field))
        self.s.flush()
        return row.id

    def get_id(self, subject: str, code: str) -> int | None:
        return self.s.scalar(
            select(LearningObjectiveRow.id).filter_by(subject=subject, code=code)
        )

    def list(self, subject: str) -> list[LearningObjective]:
        rows = self.s.scalars(
            select(LearningObjectiveRow)
            .filter_by(subject=subject)
            .order_by(LearningObjectiveRow.code)
        )
        return [_lo_from_row(r) for r in rows]

    def count(self, subject: str | None = None) -> int:
        q = select(func.count()).select_from(LearningObjectiveRow)
        if subject is not None:
            q = q.filter_by(subject=subject)
        return self.s.scalar(q) or 0


class AttemptRepo:
    def __init__(self, session: Session):
        self.s = session

    def add(self, attempt: Attempt, lo_id: int, max_points: int) -> None:
        grade = attempt.grade
        self.s.add(AttemptRow(
            id=attempt.id,
            session_id=attempt.session_id,
            item_id=attempt.item_id,
            lo_id=lo_id,
            answer=attempt.answer,
            hints_used=attempt.hints_used,
            latency_s=attempt.latency_s,
            points=grade.points if grade else None,
            max_points=max_points,
            grader=grade.grader if grade else None,
            grade=grade.model_dump(mode="json") if grade else None,
            disputed=attempt.disputed,
            exam=attempt.exam,
            created_at=attempt.created_at,
        ))
        self.s.flush()

    def list_for_lo(self, lo_id: int, include_disputed: bool = False) -> list[AttemptRow]:
        """Журнал попыток по LO в хронологическом порядке — для переигрывания θ."""
        q = select(AttemptRow).filter_by(lo_id=lo_id).order_by(AttemptRow.created_at)
        if not include_disputed:
            q = q.filter_by(disputed=False)
        return list(self.s.scalars(q))


class MasteryRepo:
    def __init__(self, session: Session):
        self.s = session

    def theta(self, lo_id: int) -> float:
        """LO без единой попытки стартует с θ = 0."""
        row = self.s.get(MasteryRow, lo_id)
        return row.theta if row else 0.0

    def attempts_count(self, lo_id: int) -> int:
        row = self.s.get(MasteryRow, lo_id)
        return row.attempts_count if row else 0

    def record(self, lo_id: int, theta: float) -> None:
        row = self.s.get(MasteryRow, lo_id)
        if row is None:
            row = MasteryRow(lo_id=lo_id, attempts_count=0)
            self.s.add(row)
        row.theta = theta
        row.attempts_count += 1
        self.s.flush()


def _lo_from_row(row: LearningObjectiveRow) -> LearningObjective:
    return LearningObjective(
        code=row.code,
        subject=row.subject,
        grade=row.grade,
        section=row.section,
        quarter=row.quarter,
        text=row.text,
        lang=row.lang,
        exam_weight=row.exam_weight,
    )
