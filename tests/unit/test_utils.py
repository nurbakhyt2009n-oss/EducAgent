from educa_agent.utils.ids import new_id, ulid
from educa_agent.utils.text import normalize


def test_new_id_has_prefix_and_ulid():
    value = new_id("att")
    prefix, body = value.split("_")
    assert prefix == "att"
    assert len(body) == 26


def test_ulid_sorts_by_time():
    assert ulid(now_ms=1_000) < ulid(now_ms=2_000) < ulid(now_ms=10**12)


def test_ulids_are_unique():
    assert len({ulid() for _ in range(1000)}) == 1000


def test_normalize_composes_kazakh_letters():
    decomposed = "й"       # и + комбинируемая бреве → й
    assert normalize(decomposed) == "й"
    assert normalize("Қазақ  тілі  ") == "Қазақ тілі"


def test_normalize_keeps_line_breaks():
    assert normalize("  строка 1 \n\tстрока   2 ") == "строка 1\nстрока 2"
