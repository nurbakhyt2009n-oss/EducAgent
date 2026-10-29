from enum import StrEnum


class ThinkingLevel(StrEnum):
    KNOWLEDGE = "knowledge_understanding"   # Знание и понимание
    APPLICATION = "application"             # Применение
    HIGHER_ORDER = "higher_order"           # Навыки высокого порядка


class AssessmentKind(StrEnum):
    PRACTICE = "practice"
    SOR = "sor"      # суммативное оценивание за раздел
    SOCH = "soch"    # суммативное оценивание за четверть


class ErrorType(StrEnum):
    CONCEPTUAL = "conceptual"
    PROCEDURAL = "procedural"
    INCOMPLETE_JUSTIFICATION = "incomplete_justification"
    TERMINOLOGY = "terminology"
    UNITS_NOTATION = "units_notation"
    MISREADING = "misreading"
    COMPUTATIONAL = "computational"
