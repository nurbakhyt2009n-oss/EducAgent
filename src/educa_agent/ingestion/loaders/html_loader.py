"""Сохранённые веб-страницы (.html): статьи учителя, например с bzfar.org.

Берётся только тело статьи (у сайтов на uCoz это блок .eText), без меню и рекламы.
Заголовки — h1–h6 и короткие абзацы целиком жирным шрифтом; код — <pre>;
таблицы переводятся в markdown.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import lxml.html

from educa_agent.ingestion.loaders.base import BlockKind, LoadedDocument, RawBlock
from educa_agent.ingestion.normalize import looks_like_code, normalize_markdown

# Где искать текст статьи — от самого точного места к самому общему.
CONTENT_XPATHS = (
    "//*[contains(concat(' ', normalize-space(@class), ' '), ' eText ')]",
    "//article",
    "//main",
    "//*[@id='content']",
    "//body",
)
SKIP = {"script", "style", "noscript", "nav", "header", "footer", "form", "button", "svg", "iframe"}
HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
BLOCK = {
    "p", "div", "section", "article", "main", "ul", "ol", "li", "pre", "table", "blockquote",
    "figure", "dl", "dt", "dd", "hr", "center", *HEADINGS,
}
BOLD = {"b", "strong"}
# В HTML строку разрывает только <br>; обычные переводы строк в исходнике — просто пробелы.
# Поэтому <br> временно помечаем отдельным символом-разделителем строк.
BR = " "


def html_text_lines(path: Path) -> list[str]:
    """Текст страницы построчно — для списков LO в формате веб-страницы."""
    return [line for block in _blocks(path)[1] for line in block[1].split("\n")]


class HtmlLoader:
    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in {".html", ".htm"}

    def load(self, path: Path) -> LoadedDocument:
        title, blocks = _blocks(path)
        raw: list[RawBlock] = []
        stack: list[tuple[int, str]] = []
        for kind, text, level in blocks:
            if kind == "heading":
                stack = [(lvl, t) for lvl, t in stack if lvl < level] + [(level, text)]
            section = tuple(t for t in [title, *(t for _, t in stack)] if t)
            raw.append(RawBlock(text, kind, 1, section))
        warnings = [] if raw else ["на странице не найден текст статьи"]
        return LoadedDocument(path=path, kind="html", unit="web", blocks=raw, warnings=warnings)


def _blocks(path: Path) -> tuple[str, list[tuple[BlockKind, str, int]]]:
    root = lxml.html.document_fromstring(path.read_bytes())
    title = (root.findtext(".//title") or "").split(" - ")[0].strip()
    container = next(
        (found[0] for xp in CONTENT_XPATHS if (found := root.xpath(xp))), root
    )
    for br in container.iter("br"):
        br.tail = BR + (br.tail or "")
    for code in container.iter("code"):
        # встроенный код в тексте: «writing `iput` instead of `input`»
        # многострочный <code> с <br> — это блок кода, его распознает _paragraph
        if BR not in code.text_content() and not any(
            _tag(a) == "pre" for a in code.iterancestors()
        ):
            text = code.text_content()
            for child in list(code):
                code.remove(child)
            code.text = f"`{text}`" if text.strip() else text
    out: list[tuple[BlockKind, str, int]] = []
    _walk(container, out)
    return title, [b for b in out if b[1]]


def _tag(el: Any) -> str:
    return el.tag.lower() if isinstance(el.tag, str) else ""


def _has_block(el: Any) -> bool:
    return any(_tag(d) in BLOCK for d in el.iterdescendants())


def _walk(el: Any, out: list[tuple[BlockKind, str, int]]) -> None:
    tag = _tag(el)
    if tag in SKIP:
        return
    if tag in HEADINGS:
        out.append(("heading", _inline(el.text_content()), HEADINGS[tag]))
    elif tag == "pre":
        code = el.text_content().replace("\r\n", "\n").replace(BR, "\n")
        out.append(("code", code.strip("\n"), 0))
    elif tag == "table":
        out.append(("table", _table(el), 0))
    elif tag in {"ul", "ol"}:
        items = [_inline(li.text_content()) for li in el if _tag(li) == "li"]
        out.append(("text", "\n".join(f"- {t}" for t in items if t), 0))
    elif not _has_block(el):
        _paragraph(el, el.text_content(), out)
    else:
        buf = [el.text or ""]
        for child in el:
            if not _tag(child):                  # <!-- комментарий --> — берём только хвост
                buf.append(child.tail or "")
            elif _tag(child) in BLOCK or _has_block(child):
                _flush(buf, out)
                _walk(child, out)
                buf = [child.tail or ""]
            elif _tag(child) not in SKIP:
                buf += [child.text_content(), child.tail or ""]
        _flush(buf, out)


def _flush(buf: list[str], out: list[tuple[BlockKind, str, int]]) -> None:
    text = "".join(buf)
    if text.strip():
        _paragraph(None, text, out)


def _paragraph(el: Any, text: str, out: list[tuple[BlockKind, str, int]]) -> None:
    if not text.strip():
        return
    lines = text.replace("\r\n", "\n").split(BR)
    # Перевод строки сразу после <br> — форматирование исходника, а не отступ кода.
    # Настоящие отступы на таких сайтах сделаны неразрывными пробелами (&nbsp;).
    code = "\n".join(
        line.lstrip("\n").replace("\n", " ").replace("\xa0", " ").rstrip() for line in lines
    )
    if looks_like_code(code.strip("\n")):
        out.append(("code", code.strip("\n"), 0))
        return
    clean = normalize_markdown("\n".join(" ".join(line.split()) for line in lines))
    if not clean:
        return
    if el is not None and _is_bold_heading(el, clean):
        out.append(("heading", clean, 3))
    else:
        out.append(("text", clean, 0))


def _is_bold_heading(el: Any, text: str) -> bool:
    """Короткий абзац, весь текст которого жирный и без точки в конце — подзаголовок."""
    if "\n" in text or len(text) > 100 or text.endswith((".", ":", ";", "?")):
        return False
    bold = "".join(b.text_content() for b in el.iter() if _tag(b) in BOLD)
    return _inline(bold) == text


def _inline(text: str) -> str:
    return " ".join(text.split())


def _table(el: Any) -> str:
    rows = []
    for tr in el.iter("tr"):
        cells = [
            _inline(c.text_content()).replace("|", "\\|") for c in tr if _tag(c) in {"td", "th"}
        ]
        if any(cells):
            rows.append("| " + " | ".join(cells) + " |")
    if not rows:
        return ""
    width = rows[0].count(" | ") + 1
    rows.insert(1, "|" + " --- |" * width)
    return "\n".join(rows)
