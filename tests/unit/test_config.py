import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from educa_agent.config import AssessmentFormat, ErrorTaxonomy, load_config
from educa_agent.domain.enums import AssessmentKind, ErrorType, ThinkingLevel


def test_shipped_config_loads(config):
    llm = config.app.llm
    assert llm.provider == "ollama"
    assert llm.active is llm.ollama
    assert llm.anthropic.tutor_model == "claude-sonnet-5-5"
    assert llm.anthropic.fast_model == "claude-haiku-5-5"
    assert "physics_10" in config.subjects


def test_error_weights_cover_taxonomy(config):
    weights = config.errors.weights
    assert set(weights) == set(ErrorType)
    assert weights[ErrorType.CONCEPTUAL] == 1.0
    assert weights[ErrorType.COMPUTATIONAL] == 0.3


def test_lo_code_pattern_matches_nis_codes(config):
    pattern = re.compile(config.nis.lo_code_pattern)
    assert pattern.findall("Цели: 10.2.1.3 и 10.2.1.4; не код: 10.2.1") == ["10.2.1.3", "10.2.1.4"]


def test_formats_cover_all_assessment_kinds(config):
    assert set(config.nis.formats) == set(AssessmentKind)
    assert set(config.nis.thinking_levels) == set(ThinkingLevel)


def test_data_dir_from_env(config, tmp_path: Path):
    assert config.paths.data == (tmp_path / "data").resolve()
    assert config.paths.db.name == "educa.db"


def test_paths_ensure_creates_raw_subdirs(config):
    config.paths.ensure()
    for sub in ("presentations", "textbooks", "objectives", "past_papers"):
        assert (config.paths.raw / sub).is_dir()


def test_unknown_subject_error_lists_known(config):
    with pytest.raises(KeyError, match="physics_10"):
        config.subject("chemistry_11")


def test_level_shares_must_sum_to_one():
    with pytest.raises(ValidationError, match="сумме 1"):
        AssessmentFormat(
            duration_min=40,
            max_points=25,
            hints_allowed=False,
            level_shares={"knowledge_understanding": 0.5, "application": 0.2},
        )


def test_taxonomy_requires_every_error_type():
    with pytest.raises(ValidationError, match="нет типов"):
        ErrorTaxonomy(types={"conceptual": {"weight": 1.0, "description": "x"}})


def test_typo_in_settings_fails_fast(tmp_path: Path, monkeypatch):
    config_dir = Path(__file__).resolve().parents[2] / "config"
    broken = tmp_path / "config"
    broken.mkdir()
    for name in ("error_taxonomy.yaml", "nis_assessment.yaml"):
        (broken / name).write_text((config_dir / name).read_text("utf-8"), "utf-8")
    text = (config_dir / "settings.yaml").read_text("utf-8")
    (broken / "settings.yaml").write_text(text.replace("hint_penalty", "hint_penalti"), "utf-8")
    monkeypatch.setenv("EDUCA_CONFIG_DIR", str(broken))

    with pytest.raises(ValidationError, match="hint_penalt"):
        load_config()
