"""Чанкинг по структуре документа.

- Слайд — один чанк. Мелкие соседние слайды с одним заголовком склеиваются.
- PDF режется по заголовкам, затем по абзацам до chunk_max_tokens с перекрытием
  в один абзац.
- Код, таблица и разобранный пример («Example» + решение) никогда не режутся пополам.

Тип чанка здесь определяется по ключевым словам; уточнять его моделью будем позже.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from educa_agent.config import IngestionSettings
from educa_agent.domain.models import ChunkType
from educa_agent.ingestion.loaders.base import LoadedDocument, RawBlock, Unit
from educa_agent.utils.text import approx_tokens

_EXAMPLE = re.compile(
    r"^\W*(worked example|example|problem|пример|задача|мысал|есеп)\b", re.I
)
_SOLUTION = re.compile(
    r"^\W*(solution|answer|output|решение|ответ|вывод программы|шешуі|жауабы)\b", re.I
)
_LO_LINE = re.compile(r"^\d{1,2}(\.\d{1,2}){3}\b")
_TYPE_RULES: list[tuple[ChunkType, re.Pattern[str]]] = [
    ("definition", re.compile(
        r"^\W*(definition|определение|анықтама)\b"
        r"|\bis (called|defined as)\b|называется|деп аталады",
        re.I,
    )),
    ("exercise", re.compile(
        r"^\W*(exercise|task|practice|activity|задание|упражнение|тапсырма|жаттығу)\b", re.I
    )),
    ("summary", re.compile(
        r"^\W*(summary|conclusion|key points|recap|итог|выводы?|қорытынды)\b", re.I
    )),
]


@dataclass
class _Piece:
    """Неделимая часть чанка: абзац, код, таблица или пример целиком."""

    text: str
    page: int
    section: tuple[str, ...]
    atomic: bool = False
    heading: bool = False
    example: bool = False

    @property
    def tokens(self) -> int:
        return approx_tokens(self.text)


@dataclass
class ChunkDraft:
    seq: int
    text: str
    chunk_type: ChunkType
    location: str                 # "slide 4" | "slides 4–5" | "p. 12" | "section: Loops"
    section_path: list[str]
    first_page: int
    last_page: int


class Chunker:
    def __init__(self, settings: IngestionSettings):
        self.min_tokens = settings.chunk_min_tokens
        self.max_tokens = settings.chunk_max_tokens

    def chunk(self, doc: LoadedDocument) -> list[ChunkDraft]:
        pieces = _group_examples([_to_piece(b) for b in doc.blocks])
        pieces = [p for big in pieces for p in self._fit(big)]
        groups = self._by_slide(pieces) if doc.unit == "slide" else self._by_section(pieces)
        drafts: list[ChunkDraft] = []
        for group in groups:
            if any(not p.heading for p in group):
                drafts.append(_draft(len(drafts), group, doc.unit))
        return drafts

    # ---------- слайды ----------

    def _by_slide(self, pieces: list[_Piece]) -> list[list[_Piece]]:
        slides: list[list[_Piece]] = []
        for p in pieces:
            if slides and slides[-1][0].page == p.page:
                slides[-1].append(p)
            else:
                slides.append([p])

        groups: list[list[_Piece]] = []
        for slide in slides:
            parts = self._by_section(slide) if _tokens(slide) > self.max_tokens else [slide]
            for part in parts:
                prev = groups[-1] if groups else None
                if (
                    prev is not None
                    and _title(prev) == _title(part)
                    and _tokens(prev) < self.min_tokens
                    and _tokens(prev) + _tokens(part) <= self.max_tokens
                ):
                    # повторный заголовок соседнего слайда не дублируем
                    prev.extend(p for p in part if not (p.heading and _title(prev)))
                else:
                    groups.append(part)
        return groups

    # ---------- PDF ----------

    def _by_section(self, pieces: list[_Piece]) -> list[list[_Piece]]:
        groups: list[list[_Piece]] = []
        cur: list[_Piece] = []

        def only_headings() -> bool:
            return all(p.heading for p in cur)

        for p in pieces:
            if p.heading and cur and not only_headings():
                groups.append(cur)
                cur = []
            elif cur and not only_headings() and _tokens(cur) + p.tokens > self.max_tokens:
                groups.append(cur)
                last = cur[-1]
                overlap = (
                    not last.atomic and not last.heading
                    and last.section == p.section
                    and last.tokens <= self.max_tokens // 3
                )
                cur = [last] if overlap else []
            cur.append(p)
        if cur:
            if only_headings() and groups:
                groups[-1].extend(cur)
            else:
                groups.append(cur)
        return self._merge_small(groups)

    def _merge_small(self, groups: list[list[_Piece]]) -> list[list[_Piece]]:
        """Короткие соседние разделы одной главы склеиваются до chunk_min_tokens."""
        merged: list[list[_Piece]] = []
        for g in groups:
            prev = merged[-1] if merged else None
            if (
                prev is not None
                and _tokens(prev) < self.min_tokens
                and _tokens(prev) + _tokens(g) <= self.max_tokens
                and prev[0].section[:1] == g[0].section[:1]
            ):
                prev.extend(g)
            else:
                merged.append(g)
        return merged

    def _fit(self, piece: _Piece) -> list[_Piece]:
        """Слишком длинный абзац режется по предложениям. Атомарные блоки — нет."""
        if piece.atomic or piece.heading or piece.tokens <= self.max_tokens:
            return [piece]
        sentences = re.split(r"(?<=[.!?])\s+", piece.text)
        out: list[_Piece] = []
        buf = ""
        for s in sentences:
            if buf and approx_tokens(buf + " " + s) > self.max_tokens:
                out.append(_Piece(buf, piece.page, piece.section))
                buf = s
            else:
                buf = f"{buf} {s}".strip()
        if buf:
            out.append(_Piece(buf, piece.page, piece.section))
        return out


def _to_piece(block: RawBlock) -> _Piece:
    if block.kind == "heading":
        return _Piece(f"## {block.text}", block.page, block.section_path, heading=True)
    if block.kind == "code":
        return _Piece(f"```\n{block.text}\n```", block.page, block.section_path, atomic=True)
    if block.kind == "table":
        return _Piece(block.text, block.page, block.section_path, atomic=True)
    if block.kind == "notes":
        return _Piece(f"Teacher notes: {block.text}", block.page, block.section_path)
    return _Piece(block.text, block.page, block.section_path)


def _group_examples(pieces: list[_Piece]) -> list[_Piece]:
    """«Example» + следующий за ним код, таблица или решение — один атомарный кусок."""
    out: list[_Piece] = []
    for p in pieces:
        prev = out[-1] if out else None
        if (
            prev is not None
            and prev.example
            and not p.heading
            and (p.atomic or _SOLUTION.match(p.text))
        ):
            prev.text = f"{prev.text}\n\n{p.text}"
        elif not p.heading and not p.atomic and _EXAMPLE.match(p.text):
            out.append(_Piece(p.text, p.page, p.section, atomic=True, example=True))
        else:
            out.append(p)
    return out


def _tokens(group: list[_Piece]) -> int:
    return sum(p.tokens for p in group)


def _title(group: list[_Piece]) -> str:
    return next((p.text for p in group if p.heading), "")


def _chunk_type(group: list[_Piece]) -> ChunkType:
    body = [p for p in group if not p.heading]
    examples = sum(p.tokens for p in body if p.example)
    if examples * 2 >= _tokens(body):
        return "worked_example"
    # Строки с кодом цели («12.5.3.2 perform testing…») о типе ничего не говорят.
    prose = [p for p in body if not _LO_LINE.match(p.text)] or body
    headings = [p.text.removeprefix("## ") for p in group if p.heading]
    for chunk_type, rule in _TYPE_RULES:
        if rule.search(prose[0].text) or any(rule.match(h) for h in headings[-1:]):
            return chunk_type
    if all(p.atomic and p.text.startswith("```") for p in body):
        return "worked_example"     # слайд с одним только кодом — образец решения
    return "theory"


def _location(unit: Unit, first: int, last: int, section: tuple[str, ...]) -> str:
    if unit == "web":
        return f"section: {section[-1]}" if section else "web page"
    if unit == "slide":
        return f"slide {first}" if first == last else f"slides {first}–{last}"
    return f"p. {first}" if first == last else f"pp. {first}–{last}"


def _draft(seq: int, group: list[_Piece], unit: Unit) -> ChunkDraft:
    first = min(p.page for p in group)
    last = max(p.page for p in group)
    return ChunkDraft(
        seq=seq,
        text="\n\n".join(p.text for p in group),
        chunk_type=_chunk_type(group),
        location=_location(unit, first, last, group[0].section),
        section_path=list(group[0].section),
        first_page=first,
        last_page=last,
    )
