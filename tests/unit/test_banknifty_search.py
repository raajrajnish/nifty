from datetime import date

import pytest

from tradingagent.sim.banknifty_search import LockBoxError, check_window, option_symbol


def test_search_refuses_lock_box_dates():
    check_window(date(2023, 12, 1), date(2025, 9, 30))           # the search window itself is fine
    with pytest.raises(LockBoxError):
        check_window(date(2023, 12, 1), date(2025, 10, 1))       # lock box 1 (latest 12 months)
    with pytest.raises(LockBoxError):
        check_window(date(2023, 11, 30), date(2025, 9, 30))      # lock box 2 (2021–23)


def test_banknifty_option_symbol():
    assert option_symbol(date(2025, 1, 29), 48500, "PE") == "NSE-BANKNIFTY-29Jan25-48500-PE"
