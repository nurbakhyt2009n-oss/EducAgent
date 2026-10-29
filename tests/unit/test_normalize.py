from educa_agent.ingestion.normalize import (
    detect_lang,
    looks_like_code,
    merge_adjacent_code,
    normalize_markdown,
    strip_repeated_lines,
)
from educa_agent.utils.text import approx_tokens

CODE = "```\ndef f(x):\n    if x  >  0:\n        return x\n```"


def test_code_indentation_and_spaces_survive():
    text = f"Some   text  here\n\n{CODE}"
    out = normalize_markdown(text)
    assert "Some text here" in out
    assert "    if x  >  0:\n        return x" in out


def test_hyphenated_line_breaks_are_joined_outside_code():
    out = normalize_markdown("An algo-\nrithm is a sequence.\n```\nx = a-\nb\n```")
    assert "algorithm" in out
    assert "x = a-\nb" in out


def test_blank_runs_collapse():
    assert normalize_markdown("a\n\n\n\n\nb") == "a\n\nb"


def test_merge_adjacent_code_blocks():
    text = "Intro\n```\ndef f(x):\n```\n\n```\n    return x\n```\nAfter"
    assert merge_adjacent_code(text) == "Intro\n```\ndef f(x):\n    return x\n```\nAfter"


def test_repeated_footer_and_page_numbers_removed_code_kept():
    pages = [
        f"Topic {i}\nreal text {i}\n```\nreturn x\n```\nNIS Informatics\n{i}" for i in range(4)
    ]
    cleaned = strip_repeated_lines(pages)
    for i, page in enumerate(cleaned):
        assert "NIS Informatics" not in page
        assert f"real text {i}" in page
        assert "return x" in page
        assert not page.rstrip().endswith(str(i))


def test_looks_like_code():
    assert looks_like_code("total = 0\nfor x in numbers:\n    total += x")
    assert looks_like_code("SELECT name\nFROM students\nWHERE grade = 11;")
    assert not looks_like_code("A loop repeats code.\nIt stops when the condition is false.")
    assert not looks_like_code("x = 1")


def test_detect_lang_ignores_code():
    assert detect_lang("A variable is a named storage location in memory.", "ru") == "en"
    assert detect_lang("Переменная — это именованная область памяти компьютера.", "en") == "ru"
    assert detect_lang("Айнымалы — жадтың атаулы аймағы, оның мәні өзгереді.", "en") == "kk"
    assert detect_lang("Tiny", "kk") == "kk"
    assert detect_lang(f"Пример:\n{CODE}", "en") == "en"   # без кода текста слишком мало


def test_approx_tokens():
    assert approx_tokens("") == 0
    assert approx_tokens("a" * 350) == 100
