import json
from pathlib import Path

import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from builders import make_objectives_xlsx, make_pdf, make_pptx
from educa_agent.ingestion.pipeline import IngestionPipeline
from educa_agent.interfaces.cli import app
from educa_agent.memory.db.session import make_engine, make_session_factory, upgrade
from educa_agent.memory.db.tables import ChunkLO, ChunkRow, Document

pytestmark = pytest.mark.integration


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    for sub in ("presentations", "textbooks", "objectives", "past_papers"):
        (raw / sub).mkdir(parents=True)
    make_pptx(raw / "presentations" / "loops.pptx")
    make_pdf(raw / "textbooks" / "book.pdf")
    make_objectives_xlsx(raw / "objectives" / "lo.xlsx")
    (raw / "past_papers" / "sor1.pdf").write_bytes(b"%PDF-1.4 stub")
    (raw / "notes.txt").write_text("not supported", encoding="utf-8")
    return raw


@pytest.fixture
def sessions(config):
    url = config.paths.db_url
    config.paths.ensure()
    upgrade(url)
    engine = make_engine(url)
    yield make_session_factory(engine)
    engine.dispose()


def _pipeline(config, sessions):
    return IngestionPipeline(config, sessions, "informatics_11")


def test_first_run_ingests_everything(config, sessions, raw):
    report = _pipeline(config, sessions).run(raw)

    assert sorted(report.new) == [
        "objectives/lo.xlsx", "presentations/loops.pptx", "textbooks/book.pdf"
    ]
    assert report.failed == []
    assert ("past_papers/sor1.pdf", "образцы СОР/СОЧ разбираются на этапе 2") in report.skipped
    assert ("notes.txt", "неподдерживаемый формат") in report.skipped
    assert report.objectives_total == 3
    assert report.chunks_total == report.chunks_written > 0
    assert report.scanned_pages == {"textbooks/book.pdf": [5]}
    assert report.image_only_slides == {"presentations/loops.pptx": [4]}

    # на слайде прямо написан код 11.2.1.1 — явная привязка
    assert report.explicit_links == 1
    assert report.uncovered == ["11.2.1.2", "11.3.1.1"]

    with sessions() as s:
        chunks = s.scalars(select(ChunkRow).order_by(ChunkRow.source_id, ChunkRow.seq)).all()
        assert {c.lang for c in chunks} == {"en"}
        assert any(c.location == "slides 1–2" for c in chunks)
        assert any(c.chunk_type == "worked_example" for c in chunks)
        assert s.scalar(select(ChunkLO.score)) == 1.0

    processed = list((config.paths.processed / "informatics_11").glob("*.json"))
    assert len(processed) == 2
    data = json.loads(processed[0].read_text("utf-8"))
    assert data["chunks"] and {"seq", "lang", "text", "location"} <= data["chunks"][0].keys()


def test_second_run_skips_unchanged(config, sessions, raw):
    first = _pipeline(config, sessions).run(raw)
    second = _pipeline(config, sessions).run(raw)
    assert second.new == second.changed == []
    assert len(second.unchanged) == 3
    assert second.chunks_written == 0
    assert second.chunks_total == first.chunks_total
    assert second.explicit_links == 1


def test_changed_and_removed_files(config, sessions, raw):
    first = _pipeline(config, sessions).run(raw)
    make_pdf(raw / "textbooks" / "book.pdf", pages=2, scanned=False)   # учебник обновили
    (raw / "presentations" / "loops.pptx").unlink()                      # презентацию удалили

    report = _pipeline(config, sessions).run(raw)
    assert report.changed == ["textbooks/book.pdf"]
    assert report.removed == ["presentations/loops.pptx"]
    assert report.scanned_pages == {}
    assert report.chunks_total < first.chunks_total
    assert report.explicit_links == 0
    with sessions() as s:
        assert s.scalar(select(Document).filter_by(kind="pptx")) is None
        assert s.scalars(select(ChunkLO)).all() == []


def test_broken_file_does_not_stop_others(config, sessions, raw):
    (raw / "textbooks" / "broken.pdf").write_bytes(b"this is not a pdf")
    report = _pipeline(config, sessions).run(raw)
    assert [rel for rel, _ in report.failed] == ["textbooks/broken.pdf"]
    assert "presentations/loops.pptx" in report.new
    assert report.chunks_total > 0


def test_cli_ingest_end_to_end(config, raw):
    runner = CliRunner()
    assert runner.invoke(app, ["init"]).exit_code == 0
    result = runner.invoke(app, ["ingest", "--subject", "informatics_11", str(raw)])
    assert result.exit_code == 0, result.output
    assert "Ingest · informatics_11" in result.output
    assert "нужен OCR" in result.output

    unknown = runner.invoke(app, ["ingest", "-s", "biology_9", str(raw)])
    assert unknown.exit_code == 1
    assert "informatics_11" in unknown.output


def test_force_reprocesses_unchanged(config, sessions, raw):
    first = _pipeline(config, sessions).run(raw)
    forced = _pipeline(config, sessions).run(raw, force=True)
    assert forced.unchanged == []
    assert len(forced.changed) == 3
    assert forced.chunks_written == first.chunks_written
    assert forced.chunks_total == first.chunks_total      # без дубликатов
