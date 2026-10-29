"""Чистка текста перед чанкингом.

Код внутри ``` не трогаем: отступы в Python значимы, а пробелы в SQL и HTML —
часть ответа, который потом будет сверяться с решением ученика.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from functools import lru_cache

from educa_agent.domain.models import Lang

_FENCE = re.compile(r"^\s*```")
_INNER_SPACES = re.compile(r"(?<=\S)[ \t ]{2,}")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_BLANK_RUNS = re.compile(r"\n{3,}")
_PAGE_NUMBER = re.compile(r"^\s*(?:page\s+|стр\.?\s*|с\.\s*)?\d{1,4}(?:\s*/\s*\d{1,4})?\s*$", re.I)

# Признаки строки кода для информатики: Python, Pascal, C-подобные, SQL, HTML.
_CODE_LINE = re.compile(
    r"""^\s*(
        def\s|class\s|for\s|while\s|if\s|elif\s|else\s*:|try\s*:|except|return\b|
        import\s|from\s\S+\s+import|print\(|input\(|
        begin\b|end[.;]|var\s|writeln|readln|
        \#include|int\s+\w|using\s|
        SELECT\s|INSERT\s|UPDATE\s|DELETE\s|CREATE\s|FROM\s|WHERE\s|
        </?[a-z][\w-]*[\s>]|
        [\w\[\]\.]+\s*(=|\+=|-=)\s*\S
    )""",
    re.X | re.I,
)
_CODE_END = re.compile(r"[:;{}]\s*$")


def _split_fences(text: str) -> list[tuple[bool, str]]:
    """Режет текст на куски (это_код, текст) по ``` ограждениям."""
    parts: list[tuple[bool, str]] = []
    buf: list[str] = []
    in_code = False
    for line in text.split("\n"):
        if _FENCE.match(line):
            if in_code:
                buf.append(line)
                parts.append((True, "\n".join(buf)))
                buf = []
            else:
                if buf:
                    parts.append((False, "\n".join(buf)))
                buf = [line]
            in_code = not in_code
            continue
        buf.append(line)
    if buf:
        parts.append((in_code, "\n".join(buf)))
    return parts


def normalize_markdown(text: str) -> str:
    """NFC, склейка переносов, лишние пробелы и пустые строки — только вне кода."""
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    out = []
    for is_code, part in _split_fences(text):
        if is_code:
            out.append("\n".join(line.rstrip() for line in part.split("\n")))
            continue
        part = _HYPHEN_BREAK.sub(r"\1\2", part)
        lines = [_INNER_SPACES.sub(" ", line).rstrip() for line in part.split("\n")]
        out.append("\n".join(lines))
    return _BLANK_RUNS.sub("\n\n", "\n".join(out)).strip("\n")


def merge_adjacent_code(text: str) -> str:
    """pymupdf4llm оборачивает каждую строку кода в свой ```-блок — склеиваем соседние."""
    return _ADJACENT_FENCES.sub("\n", text)


_ADJACENT_FENCES = re.compile(r"\n```[ \t]*\n(?:[ \t]*\n)*```\w*[ \t]*\n")


def strip_repeated_lines(pages: list[str], min_share: float = 0.6) -> list[str]:
    """Убирает колонтитулы и номера страниц: короткие строки на большинстве страниц.

    Строки кода не трогаем: `return x` вполне может встречаться на каждой странице.
    """
    if len(pages) < 3:
        return [_drop_lines(p, set()) for p in pages]
    counts: Counter[str] = Counter()
    for page in pages:
        counts.update({s for s in _prose_lines(page) if len(s) <= 80})
    threshold = max(2, int(len(pages) * min_share))
    repeated = {line for line, n in counts.items() if n >= threshold}
    return [_drop_lines(page, repeated) for page in pages]


def _prose_lines(page: str) -> list[str]:
    return [
        line.strip()
        for is_code, part in _split_fences(page)
        if not is_code
        for line in part.split("\n")
        if line.strip()
    ]


def _drop_lines(page: str, repeated: set[str]) -> str:
    out = []
    for is_code, part in _split_fences(page):
        if is_code:
            out.append(part)
            continue
        kept = [
            line for line in part.split("\n")
            if line.strip() not in repeated and not _PAGE_NUMBER.match(line)
        ]
        out.append("\n".join(kept))
    return "\n".join(out)


def looks_like_code(text: str) -> bool:
    """Хотя бы 2 строки, и больше половины похожи на код."""
    lines = [line for line in text.split("\n") if line.strip()]
    if len(lines) < 2:
        return False
    hits = sum(1 for line in lines if _CODE_LINE.match(line) or _CODE_END.search(line))
    return hits / len(lines) > 0.5


@lru_cache(maxsize=1)
def _detector():
    from lingua import Language, LanguageDetectorBuilder

    return LanguageDetectorBuilder.from_languages(
        Language.ENGLISH, Language.RUSSIAN, Language.KAZAKH
    ).build()


_LINGUA_TO_LANG: dict[str, Lang] = {"ENGLISH": "en", "RUSSIAN": "ru", "KAZAKH": "kk"}


def detect_lang(text: str, default: Lang) -> Lang:
    """Язык чанка без кода. Короткий текст — язык предмета по умолчанию."""
    prose = "\n".join(part for is_code, part in _split_fences(text) if not is_code)
    if len(prose.strip()) < 20:
        return default
    found = _detector().detect_language_of(prose)
    return _LINGUA_TO_LANG.get(found.name, default) if found else default
