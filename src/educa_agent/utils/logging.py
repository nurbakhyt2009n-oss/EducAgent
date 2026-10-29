import sys
from pathlib import Path

from loguru import logger


def setup_logging(level: str = "INFO", log_dir: Path | None = None) -> None:
    """Короткий лог в консоль, подробный — в data/logs/educa.log."""
    logger.remove()
    logger.add(sys.stderr, level=level, format="<level>{level: <8}</level> {message}")
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_dir / "educa.log",
            level="DEBUG",
            rotation="5 MB",
            retention=5,
            encoding="utf-8",
        )
