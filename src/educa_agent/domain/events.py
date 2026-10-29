"""События между слоями. Evaluation Loop публикует, Tutor Engine и память читают."""

from datetime import datetime

from pydantic import BaseModel

from educa_agent.domain.enums import ErrorType


class AttemptGraded(BaseModel):
    attempt_id: str
    session_id: str
    lo_code: str
    points: float
    max_points: int
    theta_before: float
    theta_after: float
    ts: datetime


class MistakeLogged(BaseModel):
    mistake_id: str
    attempt_id: str
    lo_code: str
    error_type: ErrorType
    misconception_id: str | None = None
    ts: datetime


class SessionClosed(BaseModel):
    session_id: str
    ended_at: datetime
    attempts: int
    lo_codes: list[str]
