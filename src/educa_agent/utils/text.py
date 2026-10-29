import re
import unicodedata

_SPACES = re.compile(r"[ \t ]+")


def normalize(text: str) -> str:
    """NFC сохраняет казахские буквы (ә, ғ, қ, ң, ө, ұ, ү, һ, і) одним символом."""
    text = unicodedata.normalize("NFC", text)
    lines = (_SPACES.sub(" ", line).strip() for line in text.splitlines())
    return "\n".join(lines).strip()
