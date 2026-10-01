import shutil
from datetime import datetime
from pathlib import Path

import pytest

from tradingagent.config import AppConfig, load_config
from tradingagent.core.clock import IST, SimClock

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    d = tmp_path / "config"
    shutil.copytree(REPO / "config", d)
    return d


@pytest.fixture
def cfg(config_dir: Path) -> AppConfig:
    return load_config(config_dir)


@pytest.fixture
def clock() -> SimClock:
    return SimClock(datetime(2026, 9, 29, 8, 0, tzinfo=IST))
