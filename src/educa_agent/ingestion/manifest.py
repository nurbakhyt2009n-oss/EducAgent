"""Манифест: SHA-256 каждого файла. Неизменённые файлы при повторном ingest пропускаются."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

SourceKind = Literal["pptx", "pdf", "html", "objectives", "past_paper"]

_MATERIALS: dict[str, SourceKind] = {
    ".pptx": "pptx", ".pdf": "pdf", ".html": "html", ".htm": "html"
}
_OBJECTIVES = {".xlsx", ".csv", ".docx", ".pdf", ".html", ".htm"}
_PAST_PAPERS = {".pdf", ".docx", ".pptx"}


@dataclass(frozen=True)
class SourceFile:
    path: Path
    key: str            # абсолютный путь в posix-виде — ключ документа в базе
    rel: str            # путь относительно data/raw — для отчётов
    kind: SourceKind
    sha256: str


@dataclass
class ManifestDiff:
    new: list[SourceFile] = field(default_factory=list)
    changed: list[SourceFile] = field(default_factory=list)
    unchanged: list[SourceFile] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)       # ключи документов


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def classify(rel: Path) -> SourceKind | None:
    """Тип файла по папке: objectives/ — списки LO, past_papers/ — образцы СОР/СОЧ."""
    suffix = rel.suffix.lower()
    folder = rel.parts[0].lower() if len(rel.parts) > 1 else ""
    if folder == "objectives":
        return "objectives" if suffix in _OBJECTIVES else None
    if folder == "past_papers":
        return "past_paper" if suffix in _PAST_PAPERS else None
    if suffix in _MATERIALS:
        return _MATERIALS[suffix]
    if suffix in {".xlsx", ".csv"}:
        return "objectives"
    return None


def scan(raw_dir: Path) -> tuple[list[SourceFile], list[str]]:
    """Все поддерживаемые файлы в raw_dir и список пропущенных (rel)."""
    files: list[SourceFile] = []
    ignored: list[str] = []
    for path in sorted(raw_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(raw_dir)
        if path.name.startswith(("~$", ".")):          # временные файлы Office, скрытые
            continue
        kind = classify(rel)
        if kind is None:
            ignored.append(rel.as_posix())
            continue
        files.append(SourceFile(
            path=path,
            key=path.resolve().as_posix(),
            rel=rel.as_posix(),
            kind=kind,
            sha256=sha256_file(path),
        ))
    return files, ignored


def diff(
    files: list[SourceFile], known: dict[str, tuple[str, str]], subject: str
) -> ManifestDiff:
    """known: ключ → (sha256, предмет) для документов, лежащих в той же папке raw."""
    result = ManifestDiff()
    for f in files:
        prev = known.get(f.key)
        if prev is None:
            result.new.append(f)
        elif prev != (f.sha256, subject):
            result.changed.append(f)
        else:
            result.unchanged.append(f)
    present = {f.key for f in files}
    result.removed = sorted(
        k for k, (_, subj) in known.items() if subj == subject and k not in present
    )
    return result
