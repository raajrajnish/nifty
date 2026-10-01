from datetime import date

import pandas as pd

from tradingagent.sim.entry_study import ENTRIES, EXITS, FILTERS
from tradingagent.sim.forward import FORWARD_RULES, FREEZE_DATE, select


def test_frozen_rules_reference_existing_components():
    for r in FORWARD_RULES:
        assert r.entry in ENTRIES and r.exit in EXITS and r.filter in FILTERS


def test_freeze_date_is_fixed():
    # changing this would silently mix seen and unseen data — must be a deliberate, documented change
    assert date(2026, 10, 1) == FREEZE_DATE


def test_v2_rules_select_setup_and_open_outside():
    from tradingagent.sim.forward import FORWARD_RULES_V2, select_v2

    t = pd.DataFrame([
        {"setup": "S1", "F4_open_outside": True, "net_inr": 1},
        {"setup": "S1", "F4_open_outside": False, "net_inr": 2},
        {"setup": "S2", "F4_open_outside": True, "net_inr": 3},
    ])
    got = {r.name: select_v2(t, r)["net_inr"].tolist() for r in FORWARD_RULES_V2}
    assert got == {"G1_S1_open_outside": [1], "G2_S2_open_outside": [3]}


def test_select_applies_entry_exit_and_filter():
    t = pd.DataFrame([
        {"entry": "orb15", "exit": "no_progress_30m", "narrow_or": True, "high_vol": False, "net_inr": 1},
        {"entry": "orb15", "exit": "no_progress_30m", "narrow_or": False, "high_vol": False, "net_inr": 2},
        {"entry": "orb15", "exit": "hold_1510", "narrow_or": True, "high_vol": False, "net_inr": 3},
        {"entry": "twap_pullback", "exit": "hold_1510", "narrow_or": False, "high_vol": False, "net_inr": 4},
    ])
    got = {r.name: select(t, r)["net_inr"].tolist() for r in FORWARD_RULES}
    assert got == {"F1_orb15_narrow_noprog": [1], "F2_orb15_narrow_hold": [3], "F3_twap_lowvol_hold": [4]}
