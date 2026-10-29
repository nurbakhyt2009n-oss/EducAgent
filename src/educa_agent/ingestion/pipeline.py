"""Оркестратор Ingestion: файл → загрузка → нормализация → чанки → SQLite.

Шаги:
1. Манифест: SHA-256 файлов, неизменённые пропускаются, удалённые — убираются из базы.
2. Сначала списки LO (чтобы при привязке чанков все коды уже были в базе).
3. Презентации и PDF: загрузка, чанкинг, определение языка, запись.
   Каждый файл — своя транзакция: ошибка в одном не ломает остальные.
4. Привязка чанков к LO по явно упомянутым кодам целей и отчёт о покрытии.

Эмбеддинги, ChromaDB и семантическая привязка к LO добавятся следующим шагом этапа 1.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session, sessionmaker

from educa_agent.config import Config
from educa_agent.domain.models import Chunk
from educa_agent.ingestion import manifest
from educa_agent.ingestion.chunker import Chunker
from educa_agent.ingestion.loaders.base import DocumentLoader
from educa_agent.ingestion.loaders.html_loader import HtmlLoader
from educa_agent.ingestion.loaders.lo_loader import LOLoader
from educa_agent.ingestion.loaders.pdf_loader import PdfLoader
from educa_agent.ingestion.loaders.pptx_loader import PptxLoader
from educa_agent.ingestion.normalize import detect_lang
from educa_agent.memory.db.repositories import ChunkRepo, DocumentRepo, LORepo


@dataclass
class IngestReport:
    subject: str
    new: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    chunks_written: int = 0
    chunk_types: Counter[str] = field(default_factory=Counter)
    objectives_parsed: int = 0
    chunks_total: int = 0
    objectives_total: int = 0
    explicit_links: int = 0
    uncovered: list[str] = field(default_factory=list)
    scanned_pages: dict[str, list[int]] = field(default_factory=dict)
    image_only_slides: dict[str, list[int]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def document_id(key: str) -> str:
    """Стабильный id документа по пути: переиндексация не плодит дубликаты."""
    return "doc_" + hashlib.sha256(key.encode()).hexdigest()[:20]


def chunk_id(doc_id: str, seq: int) -> str:
    return "chk_" + hashlib.sha256(f"{doc_id}:{seq}".encode()).hexdigest()[:20]


class IngestionPipeline:
    def __init__(self, config: Config, sessions: sessionmaker[Session], subject_id: str):
        self.config = config
        self.sessions = sessions
        self.subject = config.subject(subject_id)
        settings = config.app.ingestion
        self.chunker = Chunker(settings)
        self.loaders: dict[str, DocumentLoader] = {
            "pptx": PptxLoader(),
            "pdf": PdfLoader(scan_min_chars=settings.scan_min_chars),
            "html": HtmlLoader(),
        }
        self.lo_loader = LOLoader(config.nis.lo_code_pattern, self.subject)
        self.code_pattern = re.compile(config.nis.lo_code_pattern)
        self.processed_dir = config.paths.processed / self.subject.id

    def run(self, raw_dir: Path, force: bool = False) -> IngestReport:
        """force=True — переобработать и неизменённые файлы (после улучшения загрузчиков)."""
        raw_dir = raw_dir.resolve()
        report = IngestReport(subject=self.subject.id)
        files, ignored = manifest.scan(raw_dir)
        report.skipped += [(rel, "неподдерживаемый формат") for rel in ignored]

        prefix = raw_dir.as_posix().rstrip("/") + "/"
        with self.sessions() as s:
            known = DocumentRepo(s).known_under(prefix)
        plan = manifest.diff(files, known, self.subject.id)
        if force:
            plan.changed += plan.unchanged
            plan.unchanged = []
        report.unchanged = [f.rel for f in plan.unchanged]

        self._remove(plan.removed, prefix, report)

        todo = plan.new + plan.changed
        changed_keys = {f.key for f in plan.changed}
        # Списки LO — первыми: чанки потом ищут в тексте уже известные коды.
        for f in sorted(todo, key=lambda f: f.kind != "objectives"):
            if f.kind == "past_paper":
                report.skipped.append((f.rel, "образцы СОР/СОЧ разбираются на этапе 2"))
                continue
            try:
                with self.sessions.begin() as s:
                    if f.kind == "objectives":
                        self._ingest_objectives(s, f, report)
                    else:
                        self._ingest_material(s, f, report)
            except Exception as e:  # noqa: BLE001 — один битый файл не должен ронять весь ingest
                # Полная трассировка — только в data/logs/educa.log, в консоли хватит отчёта.
                logger.opt(exception=e).debug("Не удалось обработать {}", f.rel)
                report.failed.append((f.rel, f"{type(e).__name__}: {e}"))
                continue
            (report.changed if f.key in changed_keys else report.new).append(f.rel)

        with self.sessions.begin() as s:
            self._link_explicit(s, report)
            chunks = ChunkRepo(s)
            report.chunks_total = chunks.count(self.subject.id)
            report.objectives_total = LORepo(s).count(self.subject.id)
            report.uncovered = chunks.uncovered_objectives(self.subject.id)
        return report

    # ---------- шаги ----------

    def _remove(self, keys: list[str], prefix: str, report: IngestReport) -> None:
        if not keys:
            return
        with self.sessions.begin() as s:
            repo = DocumentRepo(s)
            for key in keys:
                doc_id = repo.delete_by_path(key)
                if doc_id:
                    (self.processed_dir / f"{doc_id}.json").unlink(missing_ok=True)
                report.removed.append(key.removeprefix(prefix))

    def _ingest_objectives(self, s: Session, f: manifest.SourceFile, report: IngestReport) -> None:
        result = self.lo_loader.load(f.path)
        repo = LORepo(s)
        for lo in result.objectives:
            repo.upsert(lo)
        DocumentRepo(s).upsert(document_id(f.key), f.key, f.sha256, f.kind, self.subject.id)
        report.objectives_parsed += len(result.objectives)
        report.warnings += result.warnings

    def _ingest_material(self, s: Session, f: manifest.SourceFile, report: IngestReport) -> None:
        doc = self.loaders[f.kind].load(f.path)
        drafts = self.chunker.chunk(doc)
        doc_id = document_id(f.key)

        DocumentRepo(s).upsert(doc_id, f.key, f.sha256, f.kind, self.subject.id)
        rows: list[tuple[int, Chunk, str]] = []
        for d in drafts:
            chunk = Chunk(
                id=chunk_id(doc_id, d.seq),
                source_id=doc_id,
                text=d.text,
                chunk_type=d.chunk_type,
                location=d.location,
                section_path=d.section_path,
            )
            rows.append((d.seq, chunk, detect_lang(d.text, self.subject.lang)))
        ChunkRepo(s).replace_for_document(doc_id, rows)
        self._write_processed(doc_id, f, rows)

        report.chunks_written += len(rows)
        report.chunk_types.update(c.chunk_type for _, c, _ in rows)
        if doc.scanned_pages:
            report.scanned_pages[f.rel] = doc.scanned_pages
        if doc.image_only_pages:
            report.image_only_slides[f.rel] = doc.image_only_pages
        report.warnings += [f"{f.rel}: {w}" for w in doc.warnings]
        if not rows:
            report.warnings.append(f"{f.rel}: не найдено ни одного фрагмента текста")

    def _link_explicit(self, s: Session, report: IngestReport) -> None:
        """Если в чанке прямо написан код цели (часто бывает на слайдах) — привязываем."""
        lo_ids = LORepo(s).ids_by_code(self.subject.id)
        chunks = ChunkRepo(s)
        texts = chunks.texts_for_subject(self.subject.id)
        links = sorted({
            (cid, lo_ids[code])
            for cid, text in texts
            for code in self.code_pattern.findall(text)
            if code in lo_ids
        })
        chunks.replace_explicit_links([cid for cid, _ in texts], links)
        report.explicit_links = len(links)

    def _write_processed(
        self, doc_id: str, f: manifest.SourceFile, rows: list[tuple[int, Chunk, str]]
    ) -> None:
        """Копия чанков в data/processed — удобно открыть и проверить глазами."""
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "source": f.rel,
            "sha256": f.sha256,
            "chunks": [
                {"seq": seq, "lang": lang} | chunk.model_dump(exclude={"lo_codes"})
                for seq, chunk, lang in rows
            ],
        }
        (self.processed_dir / f"{doc_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
