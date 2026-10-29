import pytest
from pydantic import ValidationError

from educa_agent.domain.enums import AssessmentKind, ErrorType, ThinkingLevel
from educa_agent.domain.models import Descriptor, Diagnosis, Item


def test_diagnosis_severity_bounds():
    with pytest.raises(ValidationError):
        Diagnosis(
            error_type=ErrorType.CONCEPTUAL,
            severity=1.5,
            misconception_text="путает массу и вес",
            confidence=0.9,
        )


def test_item_json_roundtrip():
    item = Item(
        id="itm_1",
        lo_codes=["10.2.1.3"],
        kind=AssessmentKind.SOR,
        thinking_level=ThinkingLevel.APPLICATION,
        stem="Тело брошено под углом 30° к горизонту со скоростью 20 м/с. Найдите время подъёма.",
        answer_type="numeric",
        reference_answer="1.02 с",
        reference_solution="t = v₀·sin α / g = 20·0,5 / 9,8 ≈ 1,02 с",
        descriptors=[Descriptor(id="d1", text="записывает формулу времени подъёма", points=1)],
        max_points=2,
    )
    restored = Item.model_validate_json(item.model_dump_json())
    assert restored == item
    assert restored.thinking_level is ThinkingLevel.APPLICATION


def test_enums_serialize_as_values():
    assert ThinkingLevel.KNOWLEDGE == "knowledge_understanding"
    assert ErrorType("incomplete_justification") is ErrorType.INCOMPLETE_JUSTIFICATION
