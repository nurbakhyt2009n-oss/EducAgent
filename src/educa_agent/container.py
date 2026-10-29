"""Сборка зависимостей. Всё тяжёлое создаётся лениво, при первом обращении."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from educa_agent.config import Config, load_config
from educa_agent.llm.base import LLMBackend
from educa_agent.llm.client import make_llm
from educa_agent.llm.prompts import PromptRenderer
from educa_agent.memory.db.session import make_engine, make_session_factory


class Container:
    def __init__(self, config: Config):
        self.config = config

    @classmethod
    def from_env(cls, home: Path | None = None) -> Container:
        return cls(load_config(home))

    @cached_property
    def engine(self) -> Engine:
        return make_engine(self.config.paths.db_url)

    @cached_property
    def sessions(self) -> sessionmaker[Session]:
        return make_session_factory(self.engine)

    @cached_property
    def llm(self) -> LLMBackend:
        return make_llm(self.config.app.llm)

    @cached_property
    def prompts(self) -> PromptRenderer:
        return PromptRenderer(self.config.paths.prompts)
