from pathlib import Path

import pytest

from builders import (
    make_html_article,
    make_objectives_csv,
    make_objectives_docx,
    make_objectives_html,
    make_objectives_pdf,
    make_objectives_xlsx,
    make_pdf,
    make_pptx,
)
from educa_agent.ingestion.loaders.html_loader import HtmlLoader
from educa_agent.ingestion.loaders.lo_loader import LOLoader
from educa_agent.ingestion.loaders.pdf_loader import PdfLoader
from educa_agent.ingestion.loaders.pptx_loader import PptxLoader

# ---------- PPTX ----------

@pytest.fixture
def pptx_doc(tmp_path: Path):
    return PptxLoader().load(make_pptx(tmp_path / "loops.pptx"))


def test_pptx_slide_structure(pptx_doc):
    slide1 = [b for b in pptx_doc.blocks if b.page == 1]
    assert [b.kind for b in slide1] == ["heading", "text", "code", "table", "notes"]
    assert slide1[0].text == "Loops in Python"
    assert all(b.section_path == ("Loops in Python",) for b in slide1)


def test_pptx_bullets_keep_levels(pptx_doc):
    text = next(b for b in pptx_doc.blocks if b.page == 1 and b.kind == "text").text
    assert text.splitlines() == [
        "- A loop repeats a block of code. LO 11.2.1.1",
        "  - for — a fixed number of times",
    ]


def test_pptx_code_by_font_keeps_indentation(pptx_doc):
    code = next(b for b in pptx_doc.blocks if b.page == 1 and b.kind == "code")
    assert code.text == "for i in range(3):\n    print(i)"


def test_pptx_code_detected_without_mono_font(pptx_doc):
    code = next(b for b in pptx_doc.blocks if b.page == 3 and b.kind == "code")
    assert "    total += x" in code.text


def test_pptx_table_and_notes(pptx_doc):
    table = next(b for b in pptx_doc.blocks if b.kind == "table")
    assert table.text.splitlines()[0] == "| Op | Meaning |"
    assert "| % | remainder |" in table.text
    notes = next(b for b in pptx_doc.blocks if b.kind == "notes")
    assert notes.text == "Explain range() carefully."


def test_pptx_image_only_slide_reported(pptx_doc):
    assert pptx_doc.image_only_pages == [4]
    assert not [b for b in pptx_doc.blocks if b.page == 4]


# ---------- PDF ----------

@pytest.fixture
def pdf_doc(tmp_path: Path):
    return PdfLoader(scan_min_chars=50).load(make_pdf(tmp_path / "book.pdf"))


def test_pdf_scanned_page_detected(pdf_doc):
    assert pdf_doc.scanned_pages == [5]
    assert all(b.page != 5 for b in pdf_doc.blocks)


def test_pdf_section_path_from_toc(pdf_doc):
    by_page = {b.page: b.section_path for b in pdf_doc.blocks}
    assert by_page[1] == ("Unit 1. Basics",)
    assert by_page[2] == ("Unit 1. Basics", "1.1 Variables")
    assert by_page[3] == ("Unit 2. Types",)


def test_pdf_code_merged_with_indentation(pdf_doc):
    code = [b for b in pdf_doc.blocks if b.kind == "code" and b.page == 1]
    assert len(code) == 1
    assert code[0].text == "def square(x):\n    return x * x"


def test_pdf_footer_removed(pdf_doc):
    assert not any("NIS Informatics 11" in b.text for b in pdf_doc.blocks)


def test_pdf_headings_detected(pdf_doc):
    headings = [b.text for b in pdf_doc.blocks if b.kind == "heading"]
    assert "Chapter 1. Data types" in headings


# ---------- LO ----------

@pytest.fixture
def lo_loader(config):
    return LOLoader(config.nis.lo_code_pattern, config.subject("informatics_11"))


def test_lo_from_xlsx_with_header_and_sections(lo_loader, tmp_path: Path):
    result = lo_loader.load(make_objectives_xlsx(tmp_path / "lo.xlsx"))
    los = {lo.code: lo for lo in result.objectives}
    assert list(los) == ["11.2.1.1", "11.2.1.2", "11.3.1.1"]
    assert los["11.2.1.1"].text == "Use loops to solve problems"
    assert los["11.2.1.1"].section == "11.2A Programming"
    assert los["11.3.1.1"].section == "11.3B Databases"
    assert [los[c].quarter for c in los] == [1, 2, 3]
    assert los["11.2.1.1"].grade == 11
    assert los["11.2.1.1"].subject == "informatics_11"
    assert any("11.3.1.2" in w and "нет формулировки" in w for w in result.warnings)


def test_lo_from_cp1251_csv(lo_loader, tmp_path: Path):
    result = lo_loader.load(make_objectives_csv(tmp_path / "lo.csv"))
    assert [(lo.code, lo.text, lo.quarter) for lo in result.objectives] == [
        ("11.1.1.1", "Объяснять назначение операционной системы", 1),
        ("11.1.1.2", "Сравнивать типы памяти компьютера", 1),
    ]


def test_lo_from_docx_paragraphs_and_tables(lo_loader, tmp_path: Path):
    result = lo_loader.load(make_objectives_docx(tmp_path / "lo.docx"))
    los = {lo.code: lo for lo in result.objectives}
    assert los["11.4.1.1"].text == (
        "Describe the layers of the TCP/IP model and the role of each layer"
    )
    assert los["11.4.1.1"].section == "Unit 11.4 Networks"
    assert los["11.4.1.2"].text == "Explain how DNS works"
    assert los["11.4.2.1"].text == "Compare IPv4 and IPv6 addressing"


def test_lo_from_pdf_with_wrapped_lines(lo_loader, tmp_path: Path):
    result = lo_loader.load(make_objectives_pdf(tmp_path / "program.pdf"))
    los = {lo.code: lo for lo in result.objectives}
    assert los["11.5.1.1"].text == "Trace a binary search on a sorted array"
    assert los["11.5.1.1"].section == "Section 11.5 Algorithms"
    assert los["11.5.1.2"].text == "Compare bubble sort and merge sort"


def test_lo_file_without_codes_warns(lo_loader, tmp_path: Path):
    path = tmp_path / "empty.csv"
    path.write_text("Topic;Hours\nLoops;4\n", encoding="utf-8")
    result = lo_loader.load(path)
    assert result.objectives == []
    assert "не найдено ни одного кода" in result.warnings[0]


# ---------- HTML (сохранённые веб-страницы) ----------

@pytest.fixture
def html_doc(tmp_path: Path):
    return HtmlLoader().load(make_html_article(tmp_path / "loops.html"))


def test_html_takes_only_article_body(html_doc):
    text = "\n".join(b.text for b in html_doc.blocks)
    assert "Menu that must be skipped" not in text
    assert "Copyright footer" not in text
    assert "tracking" not in text
    assert html_doc.unit == "web"


def test_html_structure(html_doc):
    kinds = [(b.kind, b.text.split("\n")[0][:30]) for b in html_doc.blocks]
    assert kinds == [
        ("text", "12.5.3.5 describe a syntax err"),
        ("heading", "Types of loops"),
        ("text", "A loop repeats a block of code"),
        ("text", "Loops save time."),          # HTML-комментарии вокруг пропущены
        ("text", "Nested block."),
        ("code", "flag = True"),
        ("text", "- for — a fixed number of time"),
        ("heading", "Example"),
        ("code", "for i in range(3):"),
        ("table", "| Loop | When |"),
    ]


def test_html_inline_and_block_code(html_doc):
    para = next(b.text for b in html_doc.blocks if b.text.startswith("A loop"))
    assert "Writing `whlie` instead of `while`" in para
    codes = [b.text for b in html_doc.blocks if b.kind == "code"]
    assert codes[-1] == "for i in range(3):\n    print(i)"


def test_html_code_with_br_keeps_exact_indentation(html_doc):
    """Код из <code>…<br>…</code> без лишних пробелов и обратных кавычек."""
    code = next(b.text for b in html_doc.blocks if b.text.startswith("flag"))
    assert code == 'flag = True\nwhile flag:\n    answer = input()\n    flag = answer != "q"'


def test_html_section_path(html_doc):
    # жирный подзаголовок и <h3> одного уровня: «Example» сменяет «Types of loops»
    para = next(b for b in html_doc.blocks if b.text.startswith("A loop"))
    assert para.section_path == ("Loops in Python", "Types of loops")
    code = next(b for b in html_doc.blocks if b.text.startswith("for i"))
    assert code.section_path == ("Loops in Python", "Example")


def test_lo_from_bzfar_style_html(config, tmp_path: Path):
    loader = LOLoader(config.nis.lo_code_pattern, config.subject("computer_science_12"))
    result = loader.load(make_objectives_html(tmp_path / "cs12.html"))
    los = {lo.code: lo for lo in result.objectives}
    assert list(los) == ["12.1.2.1", "12.5.1.2"]
    assert los["12.5.1.2"].text == "create a simple expert system"   # без «Theory and Tasks»
    assert los["12.5.1.2"].section == "12.1B Expert systems"
    assert los["12.5.1.2"].quarter == 1                             # из кода раздела 12.1B
    assert los["12.1.2.1"].text == (
        "describe protection measures for data and computer systems "
        "such as firewalls, encryption, biometrics"
    )
    assert los["12.1.2.1"].quarter == 2
    assert los["12.1.2.1"].grade == 12
