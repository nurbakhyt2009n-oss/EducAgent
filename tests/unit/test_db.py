from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy.exc import IntegrityError

from educa_agent.domain.models import Attempt, GradeResult, LearningObjective
from educa_agent.memory.db.repositories import AttemptRepo, LORepo, MasteryRepo
from educa_agent.memory.db.session import (
    alembic_config,
    current_revision,
    head_revision,
    make_engine,
    upgrade,
)
from educa_agent.memory.db.tables import ItemRow, SessionRow


def _lo(text: str = "Описывать движение тела, брошенного под углом") -> LearningObjective:
    return LearningObjective(
        code="10.2.1.3", subject="physics_10", grade=10, section="Кинематика", text=text
    )


def test_migrations_match_models(tmp_path: Path):
    """Схема после миграций совпадает с tables.py — значит, миграцию не забыли."""
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    upgrade(url)
    command.check(alembic_config(url))  # падает, если модели и миграции разошлись
    engine = make_engine(url)
    assert current_revision(engine) == head_revision(url)
    engine.dispose()


def test_lo_upsert_is_idempotent(session):
    repo = LORepo(session)
    first = repo.upsert(_lo())
    second = repo.upsert(_lo(text="Новая формулировка"))
    assert first == second
    assert repo.count("physics_10") == 1
    assert repo.list("physics_10")[0].text == "Новая формулировка"


def test_attempts_listed_in_time_order_without_disputed(session):
    lo_id = LORepo(session).upsert(_lo())
    session.add(SessionRow(id="ses_1", subject="physics_10", mode="study"))
    session.add(ItemRow(
        id="itm_1", primary_lo_id=lo_id, kind="practice", thinking_level="application",
        source="manual", payload={},
    ))
    session.flush()  # без relationship() SQLAlchemy не знает порядок вставки по FK
    repo = AttemptRepo(session)
    t0 = datetime(2026, 10, 29, tzinfo=UTC)
    grade = GradeResult(points=1, max_points=2, verdicts=[], grader="deterministic")
    for i, disputed in enumerate([False, True, False]):
        repo.add(
            Attempt(
                id=f"att_{i}", session_id="ses_1", item_id="itm_1", lo_code="10.2.1.3",
                answer="t = 2v₀/g", latency_s=30, grade=grade, disputed=disputed,
                created_at=t0 + timedelta(minutes=10 - i),
            ),
            lo_id=lo_id,
            max_points=2,
        )
    assert [a.id for a in repo.list_for_lo(lo_id)] == ["att_2", "att_0"]
    assert len(repo.list_for_lo(lo_id, include_disputed=True)) == 3


def test_mastery_defaults_to_zero_and_counts_updates(session):
    lo_id = LORepo(session).upsert(_lo())
    repo = MasteryRepo(session)
    assert repo.theta(lo_id) == 0.0
    repo.record(lo_id, 0.4)
    repo.record(lo_id, 0.55)
    assert repo.theta(lo_id) == 0.55
    assert repo.attempts_count(lo_id) == 2


def test_foreign_keys_enforced(session):
    session.add(ItemRow(
        id="itm_x", primary_lo_id=999, kind="practice", thinking_level="application",
        source="manual", payload={},
    ))
    with pytest.raises(IntegrityError):
        session.flush()
