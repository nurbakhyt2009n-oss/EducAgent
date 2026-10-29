from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined


class PromptRenderer:
    """Рендер Jinja2-шаблонов из config/prompts. Пропущенная переменная — ошибка, а не пустота."""

    def __init__(self, prompts_dir: Path):
        self.dir = prompts_dir
        self._env = Environment(
            loader=FileSystemLoader(prompts_dir, encoding="utf-8"),
            undefined=StrictUndefined,
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, name: str, **context: object) -> str:
        return self._env.get_template(f"{name}.j2").render(**context).strip()

    def available(self) -> list[str]:
        return sorted(p.stem for p in self.dir.glob("*.j2"))
