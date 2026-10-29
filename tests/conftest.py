from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from educa_agent.config import Config, load_config
from educa_agent.memory.db.session import make_engine, make_session_factory
from educa_agent.memory.db.tables import Base


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Тесты не читают .env и не трогают настоящие data/ и ключ API."""
    for var in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "EDUCA_HOME", "EDUCA_CONFIG_DIR"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("EDUCA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("educa_agent.config.load_dotenv", lambda *a, **k: False)


@pytest.fixture
def config() -> Config:
    """Настоящие YAML из config/ — заодно проверяем, что они валидны."""
    return load_config()


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    with make_session_factory(engine)() as s:
        yield s
