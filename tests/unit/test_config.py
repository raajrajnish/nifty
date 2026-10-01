from pathlib import Path

import pytest
import yaml

from tradingagent.config import load_config
from tradingagent.core.errors import ConfigError
from tradingagent.core.modes import Mode


def _patch(config_dir: Path, name: str, **changes: object) -> None:
    path = config_dir / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data.update(changes)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_repo_config_loads(cfg):
    assert cfg.risk.capital_inr == 200000
    assert cfg.risk.per_trade_risk_inr == 2000
    assert cfg.risk.daily_loss_limit_inr == 6000
    assert cfg.config_hash.startswith("sha256:")


def test_tbd_fields_are_reported(cfg):
    tbd = cfg.tbd_fields()
    assert "risk.min_contract_volume" in tbd
    assert not any(t.startswith("costs.") for t in tbd)  # costs sourced 2026-10-01


def test_paper_and_live_refuse_tbd(cfg):
    for mode in (Mode.PAPER, Mode.LIVE):
        with pytest.raises(ConfigError, match="TBD"):
            cfg.assert_ready_for(mode)
    cfg.assert_ready_for(Mode.BACKTEST)  # offline modes may sweep TBD values


@pytest.mark.parametrize(("stage", "mode"), [("S1", "LIVE"), ("S2", "PAPER"), ("S3", "PAPER"), ("S0", "LIVE")])
def test_invalid_stage_mode_combo(config_dir, stage, mode):
    _patch(config_dir, "stage", stage=stage, mode=mode)
    with pytest.raises(ConfigError, match="not allowed"):
        load_config(config_dir)


def test_unknown_key_rejected(config_dir):
    _patch(config_dir, "risk", max_lotz=3)
    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_ui_must_bind_localhost(config_dir):
    _patch(config_dir, "ui", host="0.0.0.0")  # noqa: S104
    with pytest.raises(ConfigError, match="localhost"):
        load_config(config_dir)


def test_login_off_refused_in_live(config_dir):
    _patch(config_dir, "ui", require_login=False)
    _patch(config_dir, "stage", stage="S2", mode="LIVE")
    with pytest.raises(ConfigError, match="require_login"):
        load_config(config_dir)


def test_schedule_order_enforced(config_dir):
    _patch(config_dir, "schedule", square_off="15:45")
    with pytest.raises(ConfigError, match="out of order"):
        load_config(config_dir)


def test_negative_risk_rejected(config_dir):
    _patch(config_dir, "risk", per_trade_risk_pct=-1)
    with pytest.raises(ConfigError):
        load_config(config_dir)


def test_missing_file(config_dir):
    (config_dir / "costs.yaml").unlink()
    with pytest.raises(ConfigError, match="missing"):
        load_config(config_dir)
