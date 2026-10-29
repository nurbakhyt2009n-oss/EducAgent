"""Репозитории: единственное место, где SQL-строки превращаются в доменные модели."""

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from educa_agent.domain.models import Attempt, Chunk, LearningObjective
from educa_agent.memory.db.tables import (
    AttemptRow,
    ChunkLO,
    ChunkRow,
    Document,
    LearningObjectiveRow,
    MasteryRow,
)

# Привязка чанка к LO по коду цели, явно написанному в тексте, — самая надёжная.
EXPLICIT_LINK_SCORE = 1.0


class DocumentRepo:
    def __init__(self, session: Session):
        self.s = session

    def known_under(self, prefix: str) -> dict[str, tuple[str, str]]:
        """Документы, чей путь начинается с prefix: путь → (sha256, предмет)."""
        rows = self.s.execute(
            select(Document.path, Document.sha256, Document.subject)
            .where(Document.path.startswith(prefix, autoescape=True))
        )
        return {path: (sha, subject) for path, sha, subject in rows}

    def upsert(self, doc_id: str, path: str, sha256: str, kind: str, subject: str) -> None:
        row = self.s.get(Document, doc_id)
        if row is None:
            self.s.add(Document(id=doc_id, path=path, sha256=sha256, kind=kind, subject=subject))
        else:
            row.path, row.sha256, row.kind, row.subject = path, sha256, kind, subject
        self.s.flush()

    def delete_by_path(self, path: str) -> str | None:
        row = self.s.scalar(select(Document).filter_by(path=path))
        if row is None:
            return None
        doc_id = row.id
        self.s.delete(row)          # чанки и их связи с LO удалит ON DELETE CASCADE
        self.s.flush()
        return doc_id


class ChunkRepo:
    def __init__(self, session: Session):
        self.s = session

    def replace_for_document(self, doc_id: str, chunks: list[tuple[int, Chunk, str]]) -> None:
        """chunks: (порядковый номер, чанк, язык). Старые чанки документа удаляются."""
        self.s.execute(delete(ChunkRow).where(ChunkRow.source_id == doc_id))
        self.s.add_all(
            ChunkRow(
                id=c.id,
                source_id=doc_id,
                seq=seq,
                location=c.location,
                section_path=c.section_path,
                chunk_type=c.chunk_type,
                lang=lang,
                text=c.text,
            )
            for seq, c, lang in chunks
        )
        self.s.flush()

    def texts_for_subject(self, subject: str) -> list[tuple[str, str]]:
        rows = self.s.execute(
            select(ChunkRow.id, ChunkRow.text)
            .join(Document, Document.id == ChunkRow.source_id)
            .where(Document.subject == subject)
        )
        return [(cid, text) for cid, text in rows]

    def count(self, subject: str) -> int:
        q = (
            select(func.count())
            .select_from(ChunkRow)
            .join(Document, Document.id == ChunkRow.source_id)
            .where(Document.subject == subject)
        )
        return self.s.scalar(q) or 0

    def replace_explicit_links(self, chunk_ids: list[str], links: list[tuple[str, int]]) -> None:
        """Пересобирает явные привязки (score = 1.0); оценки по эмбеддингам не трогает."""
        self.s.execute(
            delete(ChunkLO).where(
                ChunkLO.chunk_id.in_(chunk_ids), ChunkLO.score >= EXPLICIT_LINK_SCORE
            )
        )
        self.s.add_all(
            ChunkLO(chunk_id=cid, lo_id=lo_id, score=EXPLICIT_LINK_SCORE) for cid, lo_id in links
        )
        self.s.flush()

    def uncovered_objectives(self, subject: str) -> list[str]:
        """Коды LO предмета, к которым не привязан ни один чанк."""
        linked = select(ChunkLO.lo_id).distinct()
        rows = self.s.scalars(
            select(LearningObjectiveRow.code)
            .where(LearningObjectiveRow.subject == subject)
            .where(LearningObjectiveRow.id.not_in(linked))
        )
        return sorted(rows, key=lambda c: tuple(int(p) for p in c.split(".")))


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

    def ids_by_code(self, subject: str) -> dict[str, int]:
        rows = self.s.execute(
            select(LearningObjectiveRow.code, LearningObjectiveRow.id).filter_by(subject=subject)
        )
        return {code: lo_id for code, lo_id in rows}

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
