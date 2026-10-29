import re
import unicodedata

_SPACES = re.compile(r"[ \t ]+")


def approx_tokens(text: str) -> int:
    """Грубая оценка числа токенов: ~3.5 символа на токен для en/ru/kk.

    Точный подсчёт зависит от модели эмбеддингов, а для границ чанков 350–700
    токенов такой точности достаточно.
    """
    return max(1, round(len(text) / 3.5)) if text else 0


def normalize(text: str) -> str:
    """NFC сохраняет казахские буквы (ә, ғ, қ, ң, ө, ұ, ү, һ, і) одним символом."""
    text = unicodedata.normalize("NFC", text)
    lines = (_SPACES.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(lines).strip()
