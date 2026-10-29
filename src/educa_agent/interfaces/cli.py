"""Команда `educa`: init, doctor, config и учебные команды следующих этапов."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.table import Table

from educa_agent import __version__
from educa_agent.container import Container
from educa_agent.domain.enums import AssessmentKind
from educa_agent.memory.db.session import current_revision, head_revision, upgrade
from educa_agent.utils.logging import setup_logging

if TYPE_CHECKING:
    from educa_agent.ingestion.pipeline import IngestReport

app = typer.Typer(
    name="educa",
    help="EducaAgent — ИИ-тьютор для подготовки к СОР и СОЧ.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()

OK, WARN, FAIL = "[green]✓[/]", "[yellow]![/]", "[red]✗[/]"


def _container() -> Container:
    try:
        return Container.from_env()
    except Exception as e:  # noqa: BLE001 — показываем любую ошибку конфига понятным текстом
        console.print(f"{FAIL} Не удалось загрузить настройки: {e}")
        raise typer.Exit(1) from e


def _version(value: bool) -> None:
    if value:
        console.print(f"educa-agent {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Версия и выход.")
    ] = False,
) -> None:
    # Консоль Windows и так печатает Unicode, а при перенаправлении в файл или pipe
    # Python берёт кодировку системы (cp1251) — кириллица в выводе ломается.
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty() and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


@app.command()
def init() -> None:
    """Создаёт папки data/ и применяет миграции базы."""
    c = _container()
    paths = c.config.paths
    paths.ensure()
    setup_logging(c.config.log_level, paths.logs)
    upgrade(paths.db_url)
    console.print(f"{OK} Папки данных: {paths.data}")
    console.print(f"{OK} База данных: {paths.db} (ревизия {current_revision(c.engine)})")
    console.print(f"Положи материалы в {paths.raw} и запусти [bold]educa doctor[/].")


@app.command()
def doctor() -> None:
    """Проверяет окружение и настройки. Ничего не меняет."""
    table = Table(show_header=True, header_style="bold")
    table.add_column("", width=2)
    table.add_column("Проверка")
    table.add_column("Результат")
    failed = False

    def row(status: str, name: str, detail: str) -> None:
        nonlocal failed
        failed |= status == FAIL
        table.add_row(status, name, detail)

    py = sys.version_info
    row(OK if py >= (3, 12) else FAIL, "Python", f"{py.major}.{py.minor}.{py.micro}")

    try:
        c = Container.from_env()
    except Exception as e:  # noqa: BLE001
        row(FAIL, "Настройки config/", str(e))
        console.print(table)
        raise typer.Exit(1) from e
    cfg, paths = c.config, c.config.paths
    llm_cfg = cfg.app.llm
    row(OK, "Настройки config/", str(paths.config))
    row(
        OK,
        f"Модели ({llm_cfg.provider})",
        f"тьютор {llm_cfg.active.tutor_model}, разметка {llm_cfg.active.fast_model}",
    )

    # LLM нужна с этапа 1, поэтому её проблемы — предупреждения, а не ошибки.
    if llm_cfg.provider == "ollama":
        from educa_agent.llm.base import LLMError
        from educa_agent.llm.ollama_client import OllamaClient

        try:
            installed = OllamaClient(llm_cfg.ollama).installed_models()
        except LLMError as e:
            row(WARN, "Ollama", str(e))
        else:
            needed = {llm_cfg.ollama.tutor_model, llm_cfg.ollama.fast_model}
            missing = sorted(m for m in needed if m not in installed)
            row(
                WARN if missing else OK,
                "Ollama",
                f"не скачаны: {', '.join(missing)} — выполни: ollama pull {missing[0]}"
                if missing else "запущена, модели скачаны",
            )
    else:
        has_key = bool(
            os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
        row(
            OK if has_key else WARN,
            "Ключ Anthropic API",
            "задан" if has_key else "не задан — скопируй .env.example в .env и впиши ключ",
        )

    if not paths.raw.is_dir():
        row(FAIL, "Папки данных", f"{paths.data} не создана — запусти educa init")
    else:
        files = sum(1 for p in paths.raw.rglob("*") if p.is_file())
        row(OK if files else WARN, "Материалы data/raw", f"файлов: {files}")

    if not paths.db.exists():
        row(FAIL, "База данных", "нет файла — запусти educa init")
    else:
        cur, head = current_revision(c.engine), head_revision(paths.db_url)
        detail = f"ревизия {cur}"
        if cur != head:
            detail += f", нужна {head} — запусти educa init"
        row(OK if cur == head else FAIL, "База данных", detail)

    prompts = c.prompts.available()
    row(OK if "tutor_system" in prompts else FAIL, "Промпты", f"шаблонов: {len(prompts)}")

    if not cfg.subjects:
        row(FAIL, "Предметы", "нет файлов в config/subjects")
    for subject in cfg.subjects.values():
        no_dates = [q for q, spec in subject.quarters.items() if spec.soch_date is None]
        row(
            WARN if no_dates else OK,
            f"Предмет {subject.id}",
            f"нет дат СОЧ для четвертей {no_dates}" if no_dates else "даты СОЧ заданы",
        )

    console.print(table)
    if failed:
        raise typer.Exit(1)


@app.command("config")
def show_config() -> None:
    """Показывает основные настройки."""
    cfg = _container().config
    console.print(f"[bold]Дом проекта:[/] {cfg.paths.home}")
    console.print(f"[bold]Данные:[/] {cfg.paths.data}")
    llm_cfg = cfg.app.llm
    console.print(f"[bold]Поставщик модели:[/] {llm_cfg.provider}")
    console.print(
        f"[bold]Модели:[/] {llm_cfg.active.tutor_model} (тьютор), "
        f"{llm_cfg.active.fast_model} (разметка)"
    )
    if llm_cfg.provider == "anthropic":
        console.print(
            f"[bold]Бюджет сессии:[/] ${llm_cfg.anthropic.budget_usd_per_session:.2f}"
        )
    console.print(f"[bold]Предметы:[/] {', '.join(cfg.subjects) or 'нет'}")


def _not_yet(stage: str) -> None:
    console.print(f"{WARN} Команда появится на этапе {stage} (см. docs/architecture.md).")
    raise typer.Exit(1)


@app.command()
def ingest(
    subject: Annotated[
        str, typer.Option("--subject", "-s", help="Предмет, например informatics_11.")
    ],
    path: Annotated[
        Path | None, typer.Argument(help="Папка с материалами (по умолчанию data/raw).")
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Переобработать все файлы, даже неизменённые.")
    ] = False,
) -> None:
    """Загружает PPTX, PDF и списки LO в базу знаний. Повторный запуск берёт только изменённое."""
    from educa_agent.ingestion.pipeline import IngestionPipeline

    c = _container()
    paths = c.config.paths
    raw_dir = path or paths.raw
    if not raw_dir.is_dir():
        console.print(f"{FAIL} Папка {raw_dir} не найдена — запусти educa init")
        raise typer.Exit(1)
    if not paths.db.exists() or current_revision(c.engine) != head_revision(paths.db_url):
        console.print(f"{FAIL} База не создана или устарела — запусти educa init")
        raise typer.Exit(1)
    try:
        c.config.subject(subject)
    except KeyError as e:
        console.print(f"{FAIL} {e.args[0]}")
        raise typer.Exit(1) from e

    setup_logging(c.config.log_level, paths.logs)
    with console.status(f"Обрабатываю {raw_dir} …"):
        report = IngestionPipeline(c.config, c.sessions, subject).run(raw_dir, force=force)
    _print_ingest_report(report)
    if report.failed:
        raise typer.Exit(1)


def _print_ingest_report(r: IngestReport) -> None:
    files = Table(title=f"Ingest · {r.subject}", show_header=False)
    files.add_row("Новые файлы", str(len(r.new)))
    files.add_row("Изменённые", str(len(r.changed)))
    files.add_row("Без изменений", str(len(r.unchanged)))
    files.add_row("Удалённые", str(len(r.removed)))
    files.add_row("Ошибки", f"[red]{len(r.failed)}[/]" if r.failed else "0")
    files.add_row("Записано чанков", str(r.chunks_written))
    files.add_row("Чанков у предмета", str(r.chunks_total))
    if r.chunk_types:
        files.add_row("Типы", ", ".join(f"{t}: {n}" for t, n in r.chunk_types.most_common()))
    files.add_row(
        "Целей обучения (LO)", f"{r.objectives_total} (прочитано из файлов: {r.objectives_parsed})"
    )
    covered = r.objectives_total - len(r.uncovered)
    files.add_row("LO с явной привязкой", f"{covered} из {r.objectives_total}")
    console.print(files)

    for rel, err in r.failed:
        console.print(f"{FAIL} {rel}: {err}")
    for rel, reason in r.skipped:
        console.print(f"{WARN} пропущен {rel}: {reason}")
    for rel, pages in r.scanned_pages.items():
        console.print(f"{WARN} {rel}: страницы-сканы без текста {pages} — нужен OCR")
    for rel, slides in r.image_only_slides.items():
        console.print(f"{WARN} {rel}: слайды только с картинками {slides}")
    for w in r.warnings:
        console.print(f"{WARN} {w}")
    if r.uncovered and r.objectives_total:
        shown = ", ".join(r.uncovered[:10]) + (" …" if len(r.uncovered) > 10 else "")
        console.print(
            f"{WARN} Без явной привязки к материалам: {shown}\n"
            "   Это нормально: явная привязка — только по коду цели в тексте. "
            "Привязка по смыслу появится вместе с эмбеддингами."
        )


@app.command()
def plan(subject: Annotated[str, typer.Option(help="Предмет, например physics_10.")]):
    """Строит план сессии по графу слабых мест."""
    _not_yet("4 · Self-Evolution")


@app.command()
def study(subject: Annotated[str | None, typer.Option(help="Предмет.")] = None):
    """Учебная сессия с сократовским тьютором."""
    _not_yet("3 · Tutor Engine")


@app.command()
def exam(
    kind: Annotated[AssessmentKind, typer.Option(help="sor или soch.")] = AssessmentKind.SOCH,
    quarter: Annotated[int, typer.Option(min=1, max=4, help="Четверть.")] = 1,
):
    """Симуляция СОР/СОЧ с таймером и без подсказок."""
    _not_yet("5 · Экзамен и дашборд")


@app.command()
def report():
    """Отчёт о прогрессе: какие LO выросли, что повторить."""
    _not_yet("4 · Self-Evolution")
