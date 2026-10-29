"""Общий формат, в который загрузчики превращают любой документ."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

# heading — заголовок слайда или раздела; notes — заметки докладчика;
# code и table — атомарные блоки, чанкер никогда не режет их пополам.
BlockKind = Literal["heading", "text", "table", "code", "notes"]
Unit = Literal["slide", "page", "web"]       # web — веб-страница без номеров страниц


@dataclass(frozen=True)
class RawBlock:
    text: str
    kind: BlockKind
    page: int                            # номер слайда или страницы, с 1
    section_path: tuple[str, ...] = ()


@dataclass
class LoadedDocument:
    path: Path
    kind: Literal["pptx", "pdf", "html"]
    unit: Unit
    blocks: list[RawBlock]
    scanned_pages: list[int] = field(default_factory=list)   # нужен OCR
    image_only_pages: list[int] = field(default_factory=list)  # только картинки, без текста
    warnings: list[str] = field(default_factory=list)


class DocumentLoader(Protocol):
    def supports(self, path: Path) -> bool: ...
    def load(self, path: Path) -> LoadedDocument: ...
