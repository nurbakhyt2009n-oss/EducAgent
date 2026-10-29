"""Списки целей обучения (LO) из xlsx, csv, docx и PDF учебной программы.

Код цели ищется регуляркой из nis_assessment.yaml (класс.раздел.подраздел.номер).
Таблицы разбираются по строкам, документы — по строкам текста; формулировка,
перенесённая на следующую строку, приклеивается к своей цели.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from educa_agent.config import SubjectConfig
from educa_agent.domain.models import LearningObjective
from educa_agent.ingestion.normalize import normalize_markdown

TABLE_SUFFIXES = {".xlsx", ".csv"}
SUFFIXES = TABLE_SUFFIXES | {".docx", ".pdf", ".html", ".htm"}

_HEADER = {
    "text": ("objective", "learning", "description", "цель", "описание", "мақсат", "сипаттама"),
    "quarter": ("quarter", "term", "четверть", "тоқсан"),
    "section": ("section", "unit", "topic", "раздел", "тема", "бөлім", "тақырып"),
}
_SECTION_LINE = re.compile(
    r"^(unit|section|chapter|раздел|глава|бөлім)\b|^\d{1,2}\.[1-4][A-Z]\b", re.I
)
# Код раздела НИШ: класс.четверть+буква, например 12.2A — второй раздел второй четверти.
_UNIT_CODE = re.compile(r"\b\d{1,2}\.([1-4])[A-Z]\b")
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4}
_TRIM = " \t.:;-–—|"


@dataclass
class LOParseResult:
    objectives: list[LearningObjective] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class _Columns:
    text: int | None = None
    quarter: int | None = None
    section: int | None = None


class LOLoader:
    def __init__(self, code_pattern: str, subject: SubjectConfig):
        self.pattern = re.compile(code_pattern)
        self.subject = subject

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in SUFFIXES

    def load(self, path: Path) -> LOParseResult:
        suffix = path.suffix.lower()
        found: list[tuple[str, str, str, int | None]] = []
        if suffix == ".xlsx":
            found += self._from_rows(_xlsx_rows(path))
        elif suffix == ".csv":
            found += self._from_rows(_csv_rows(path))
        elif suffix == ".docx":
            tables, lines = _docx_content(path)
            found += self._from_rows(tables)
            found += self._from_lines(lines)
        elif suffix == ".pdf":
            found += self._from_lines(_pdf_lines(path))
        elif suffix in {".html", ".htm"}:
            from educa_agent.ingestion.loaders.html_loader import html_text_lines

            found += self._from_lines(html_text_lines(path))
        return self._build(found, path.name)

    # ---------- таблицы ----------

    def _from_rows(self, rows: Iterator[list[str]]) -> list[tuple[str, str, str, int | None]]:
        out = []
        cols: _Columns | None = None
        current_section = ""
        for cells in rows:
            filled = [c for c in cells if c]
            if not filled:
                continue
            hit = next(
                ((i, m) for i, c in enumerate(cells) if (m := self.pattern.search(c))), None
            )
            if hit is None:
                lowered = [c.lower() for c in cells]
                if cols is None and len(filled) >= 2 and _looks_like_header(lowered):
                    cols = _header_columns(lowered)
                elif len(filled) == 1 and len(filled[0]) <= 150:
                    current_section = filled[0]
                continue

            idx, m = hit
            code = m.group(0)
            text = (cells[idx][: m.start()] + " " + cells[idx][m.end():]).strip(_TRIM)
            if cols and cols.text is not None and cols.text != idx and cells[cols.text]:
                text = cells[cols.text]
            elif len(text) < 10:
                prose = [c for i, c in enumerate(cells) if i != idx and _is_prose(c)]
                text = max(prose, key=len, default=text)

            quarter = None
            if cols and cols.quarter is not None:
                quarter = _parse_quarter(cells[cols.quarter])
            section = current_section
            if cols and cols.section is not None and cells[cols.section]:
                section = cells[cols.section]
            out.append((code, text, section, quarter))
        return out

    # ---------- сплошной текст ----------

    def _from_lines(self, lines: list[str]) -> list[tuple[str, str, str, int | None]]:
        out: list[tuple[str, str, str, int | None]] = []
        current: list[str] | None = None          # [код, части текста...]
        current_section = ""

        def flush() -> None:
            nonlocal current
            if current:
                out.append((current[0], " ".join(current[1:]).strip(_TRIM), current_section, None))
            current = None

        for line in lines:
            s = line.strip()
            m = self.pattern.search(s) if s else None
            if not s:
                flush()
            elif m and m.start() <= 3:
                flush()
                current = [m.group(0), s[m.end():].strip(_TRIM)]
            elif _SECTION_LINE.match(s):
                flush()
                current_section = s
            elif current is not None and s[0].islower():
                current.append(s)        # формулировка, перенесённая на новую строку
            else:
                flush()                  # «Theory and Tasks 2023» и прочие подписи
        flush()
        return out

    # ---------- сборка ----------

    def _build(self, found: list[tuple[str, str, str, int | None]], source: str) -> LOParseResult:
        result = LOParseResult()
        seen: dict[str, LearningObjective] = {}
        for code, text, section, quarter in found:
            text = normalize_markdown(" ".join(text.split()))
            if not text:
                result.warnings.append(f"{source}: у цели {code} нет формулировки — пропущена")
                continue
            if code in seen:
                if seen[code].text != text:
                    result.warnings.append(
                        f"{source}: цель {code} встречается дважды, взята первая"
                    )
                continue
            parts = code.split(".")
            if quarter is None and (unit := _UNIT_CODE.search(section)):
                quarter = int(unit.group(1))
            seen[code] = LearningObjective(
                code=code,
                subject=self.subject.id,
                grade=int(parts[0]),
                section=section.strip() or ".".join(parts[:2]),
                quarter=quarter,
                text=text,
                lang=self.subject.lang,
            )
        result.objectives = sorted(seen.values(), key=lambda lo: _code_key(lo.code))
        if not result.objectives:
            result.warnings.append(f"{source}: не найдено ни одного кода цели вида 11.2.1.3")
        return result


def _code_key(code: str) -> tuple[int, ...]:
    return tuple(int(p) for p in code.split("."))


def _looks_like_header(lowered: list[str]) -> bool:
    return any(hint in c for c in lowered for hints in _HEADER.values() for hint in hints)


def _header_columns(lowered: list[str]) -> _Columns:
    cols = _Columns()
    for i, c in enumerate(lowered):
        for name, hints in _HEADER.items():
            if getattr(cols, name) is None and any(h in c for h in hints):
                setattr(cols, name, i)
                break
    return cols


def _is_prose(cell: str) -> bool:
    return len(cell) >= 10 and sum(ch.isalpha() for ch in cell) >= len(cell) / 2


def _parse_quarter(cell: str) -> int | None:
    if m := re.search(r"\b([1-4])\b", cell):
        return int(m.group(1))
    if m := re.search(r"\b(IV|I{1,3})\b", cell):
        return _ROMAN[m.group(1)]
    return None


def _cell(value: object) -> str:
    return "" if value is None else " ".join(str(value).split())


def _xlsx_rows(path: Path) -> Iterator[list[str]]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                yield [_cell(v) for v in row]
    finally:
        wb.close()


def _csv_rows(path: Path) -> Iterator[list[str]]:
    data = path.read_bytes()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("cp1251")    # Excel на русской Windows сохраняет CSV так
    try:
        dialect: type[csv.Dialect] | csv.Dialect = csv.Sniffer().sniff(text[:4096], ",;\t")
    except csv.Error:
        dialect = csv.excel
    for row in csv.reader(io.StringIO(text), dialect):
        yield [_cell(v) for v in row]


def _docx_content(path: Path) -> tuple[Iterator[list[str]], list[str]]:
    from docx import Document

    doc = Document(str(path))
    rows: list[list[str]] = []
    for table in doc.tables:
        for row in table.rows:
            cells: list[str] = []
            for cell in row.cells:
                text = _cell(cell.text)
                if not cells or cells[-1] != text:   # объединённые ячейки повторяются
                    cells.append(text)
            rows.append(cells)
    return iter(rows), [p.text for p in doc.paragraphs]


def _pdf_lines(path: Path) -> list[str]:
    import pymupdf

    with pymupdf.open(path) as doc:
        return [line for page in doc for line in page.get_text().split("\n")]
