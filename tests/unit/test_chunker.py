from pathlib import Path

import pytest

from educa_agent.ingestion.chunker import Chunker
from educa_agent.ingestion.loaders.base import LoadedDocument, RawBlock


@pytest.fixture
def chunker(config):
    # маленькие границы, чтобы короткие тестовые тексты резались
    settings = config.app.ingestion.model_copy(
        update={"chunk_min_tokens": 20, "chunk_max_tokens": 60}
    )
    return Chunker(settings)


def _doc(blocks: list[RawBlock], unit="page") -> LoadedDocument:
    return LoadedDocument(path=Path("x"), kind="pdf" if unit == "page" else "pptx",
                          unit=unit, blocks=blocks)


def _para(n: int, page: int = 1, section=("Unit 1",)) -> RawBlock:
    return RawBlock(f"Paragraph {n}. " + "Loops repeat instructions. " * 3, "text", page, section)


def test_one_chunk_per_slide_with_location(chunker):
    blocks = [
        RawBlock("Variables", "heading", 1, ("Variables",)),
        RawBlock("A variable is called a named memory cell.", "text", 1, ("Variables",)),
        RawBlock("Loops", "heading", 2, ("Loops",)),
        RawBlock("Exercise: print numbers 1 to 10.", "text", 2, ("Loops",)),
    ]
    drafts = chunker.chunk(_doc(blocks, unit="slide"))
    assert [d.location for d in drafts] == ["slide 1", "slide 2"]
    assert drafts[0].text.startswith("## Variables")
    assert [d.chunk_type for d in drafts] == ["definition", "exercise"]
    assert drafts[1].section_path == ["Loops"]


def test_small_slides_with_same_title_merge(chunker):
    blocks = [
        RawBlock("Loops", "heading", 1, ("Loops",)),
        RawBlock("for repeats.", "text", 1, ("Loops",)),
        RawBlock("Loops", "heading", 2, ("Loops",)),
        RawBlock("while repeats too.", "text", 2, ("Loops",)),
    ]
    drafts = chunker.chunk(_doc(blocks, unit="slide"))
    assert len(drafts) == 1
    assert drafts[0].location == "slides 1–2"
    assert drafts[0].text.count("## Loops") == 1


def test_code_block_is_never_split(chunker):
    code = "\n".join(f"    line_{i} = {i}" for i in range(60))   # намного длиннее max
    blocks = [_para(1), RawBlock(code, "code", 1, ("Unit 1",)), _para(2)]
    drafts = chunker.chunk(_doc(blocks))
    holder = [d for d in drafts if "line_0 = 0" in d.text]
    assert len(holder) == 1
    assert "line_59 = 59" in holder[0].text
    assert holder[0].text.count("```") == 2


def test_long_section_splits_with_one_paragraph_overlap(config):
    # перекрытие берётся, только если абзац не длиннее трети чанка (~27 из 90 токенов)
    chunker = Chunker(config.app.ingestion.model_copy(
        update={"chunk_min_tokens": 20, "chunk_max_tokens": 90}
    ))
    blocks = [RawBlock("Loops", "heading", 1, ("Unit 1",))] + [_para(i) for i in range(5)]
    drafts = chunker.chunk(_doc(blocks))
    assert len(drafts) >= 2
    last_of_first = drafts[0].text.split("\n\n")[-1]
    assert drafts[1].text.startswith(last_of_first)


def test_big_paragraph_is_not_used_as_overlap(chunker):
    blocks = [_para(i) for i in range(3)]          # каждый ~27 токенов > 60 // 3
    drafts = chunker.chunk(_doc(blocks))
    texts = [d.text for d in drafts]
    assert sum(t.count("Paragraph 1.") for t in texts) == 1


def test_heading_starts_new_chunk_and_spans_pages(chunker):
    blocks = [
        RawBlock("Intro", "heading", 1, ("Intro",)),
        RawBlock("Short intro text about programs.", "text", 1, ("Intro",)),
        RawBlock("More intro on the next page.", "text", 2, ("Intro",)),
        RawBlock("Types", "heading", 3, ("Types",)),
        RawBlock("Integers and strings are data types.", "text", 3, ("Types",)),
    ]
    drafts = chunker.chunk(_doc(blocks))
    assert [d.section_path for d in drafts] == [["Intro"], ["Types"]]
    assert drafts[0].location == "pp. 1–2"
    assert drafts[1].location == "p. 3"


def test_worked_example_kept_whole(chunker):
    blocks = [
        RawBlock("Example: find the maximum of a list.", "text", 1, ("U",)),
        RawBlock("m = xs[0]\nfor x in xs:\n    if x > m:\n        m = x", "code", 1, ("U",)),
        RawBlock("Answer: m holds the maximum.", "text", 1, ("U",)),
    ]
    drafts = chunker.chunk(_doc(blocks))
    assert len(drafts) == 1
    assert drafts[0].chunk_type == "worked_example"
    assert "Answer: m holds" in drafts[0].text


def test_teacher_notes_are_labelled(chunker):
    blocks = [
        RawBlock("Recursion", "heading", 1, ("Recursion",)),
        RawBlock("A function that calls itself.", "text", 1, ("Recursion",)),
        RawBlock("Draw the call stack.", "notes", 1, ("Recursion",)),
    ]
    drafts = chunker.chunk(_doc(blocks, unit="slide"))
    assert "Teacher notes: Draw the call stack." in drafts[0].text


def test_headings_only_produce_no_chunks(chunker):
    blocks = [RawBlock("Unit 1", "heading", 1, ()), RawBlock("Unit 2", "heading", 2, ())]
    assert chunker.chunk(_doc(blocks)) == []
