"""PDF: постраничный markdown (pymupdf4llm), путь раздела из оглавления.

Страница почти без текста, но с картинками — скан. OCR пока не делается:
такие страницы попадают в отчёт, чтобы было видно, какой материал не прочитан.
"""

from __future__ import annotations

import re
from pathlib import Path

import pymupdf
import pymupdf4llm

from educa_agent.ingestion.loaders.base import BlockKind, LoadedDocument, RawBlock
from educa_agent.ingestion.normalize import (
    merge_adjacent_code,
    normalize_markdown,
    strip_repeated_lines,
)

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")


class PdfLoader:
    def __init__(self, scan_min_chars: int = 50):
        self.scan_min_chars = scan_min_chars

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def load(self, path: Path) -> LoadedDocument:
        with pymupdf.open(path) as doc:
            toc = [(lvl, title.strip(), page) for lvl, title, page in doc.get_toc() if page >= 1]
            text_sizes = [len(page.get_text().strip()) for page in doc]
            has_images = [bool(page.get_images()) for page in doc]
            page_count = doc.page_count

        pages = pymupdf4llm.to_markdown(
            str(path), page_chunks=True, use_ocr=False,
            header=False, footer=False, show_progress=False,
        )
        texts = strip_repeated_lines([merge_adjacent_code(p["text"]) for p in pages])

        scanned = [
            n for n in range(1, page_count + 1)
            if text_sizes[n - 1] < self.scan_min_chars and has_images[n - 1]
        ]
        toc_paths = _toc_paths(toc, page_count) if toc else None

        blocks: list[RawBlock] = []
        heading_stack: list[str] = []
        for n, text in enumerate(texts, start=1):
            if n in scanned:
                continue
            for kind, body, level in _parse_markdown(normalize_markdown(text)):
                if kind == "heading" and toc_paths is None:
                    heading_stack = heading_stack[: level - 1] + [body]
                section = toc_paths[n] if toc_paths is not None else tuple(heading_stack)
                blocks.append(RawBlock(body, kind, n, section))

        return LoadedDocument(
            path=path, kind="pdf", unit="page", blocks=blocks, scanned_pages=scanned
        )


def _toc_paths(toc: list[tuple[int, str, int]], page_count: int) -> dict[int, tuple[str, ...]]:
    """Для каждой страницы — путь раздела: последний пункт оглавления на каждом уровне."""
    paths: dict[int, tuple[str, ...]] = {}
    stack: list[str] = []
    i = 0
    for page in range(1, page_count + 1):
        while i < len(toc) and toc[i][2] <= page:
            level, title, _ = toc[i]
            stack = stack[: level - 1] + [title]
            i += 1
        paths[page] = tuple(stack)
    return paths


def _parse_markdown(text: str) -> list[tuple[BlockKind, str, int]]:
    """Markdown страницы → блоки (вид, текст, уровень заголовка)."""
    blocks: list[tuple[BlockKind, str, int]] = []
    lines = text.split("\n")
    para: list[str] = []

    def flush_para() -> None:
        if para:
            blocks.append(("text", "\n".join(para).strip(), 0))
            para.clear()

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_para()
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            if any(c.strip() for c in code):
                blocks.append(("code", "\n".join(code).strip("\n"), 0))
        elif stripped.startswith("|"):
            flush_para()
            table: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table.append(lines[i].strip())
                i += 1
            blocks.append(("table", "\n".join(table), 0))
            continue
        elif (m := _HEADING.match(stripped)) is not None:
            flush_para()
            blocks.append(("heading", m.group(2).strip("* "), len(m.group(1))))
        elif not stripped:
            flush_para()
        else:
            para.append(line)
        i += 1
    flush_para()
    return [b for b in blocks if b[1]]
