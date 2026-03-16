"""
tests/test_07_stop_orders.py
-----------------------------
Stop order trigger logic — stop_buy and stop_sell.

Covers
------
S7.3  stop_buy triggers on confirmed crossover (prev_close < level, current high >= level)
T7.2  stop_buy candle 0 skipped — no prev_close to confirm direction
T7.3  stop_buy no crossover — price always above level, no trigger
T7.4  stop_buy never triggers → price_path_captured=False
T7.5  stop_sell triggers on confirmed crossover (prev_close > level, current low <= level)
T7.6  stop_sell candle 0 skipped — no prev_close
T7.7  stop_sell never triggers → price_path_captured=False

Key rules guarded (EC2)
-----------------------
stop_buy:  prev_close < lp AND current max(op,hi,cl) >= lp
           → requires price to have been BELOW the level and now crossing UP
           → candle 0 is skipped (prev_close is None → condition is False)
           → prevents false trigger when price already at/above level at candle 0

stop_sell: prev_close > lp AND current min(op,lo,cl) <= lp
           → requires price to have been ABOVE the level and now crossing DOWN
           → candle 0 skipped identically

This is different from limit orders which check from candle 0 with no direction confirm.

Setup
-----
stop_buy:  want to buy breakout ABOVE 1.10200 (current price below)
           SL=1.10100 (10 pip below stop = 1R), TP=1.10400 (20 pip above = 2R)

stop_sell: want to sell breakdown BELOW 1.09800 (current price above)
           SL=1.09900 (10 pip above stop = 1R), TP=1.09600 (20 pip below = 2R)
"""

import pytest
from tests.helpers import (
    make_candles, trade_params, assert_outcome,
    ENTRY_TIME, mfe_calculator,
)

STOP_BUY = dict(
    trade_type="stop_buy",
    entry_price=1.10200,       # ignored — actual_entry = limit_price after trigger
    limit_price=1.10200,       # stop level (breakout above this)
    stoploss_price=1.10100,    # 10 pip below stop = 1R
    takeprofit_price=1.10400,  # 20 pip above stop = 2R
)

STOP_SELL = dict(
    trade_type="stop_sell",
    entry_price=1.09800,
    limit_price=1.09800,       # stop level (breakdown below this)
    stoploss_price=1.09900,    # 10 pip above stop = 1R
    takeprofit_price=1.09600,  # 20 pip below stop = 2R
)


# ── T7.1: stop_buy triggers on confirmed crossover (S7.3) ─────────────────────

def test_stop_buy_triggers_on_crossover(inject_candles):
    """
    S7.3: prev_close=1.10150 < stop 1.10200, then high=1.10210 >= 1.10200.
    Confirmed crossover → triggers. Trade then hits TP.

    Candle 0 (offset 1): close=1.10150 → becomes prev_close for candle 1.
    Candle 1 (offset 2): high=1.10210 >= 1.10200, prev_close=1.10150 < 1.10200 → trigger.
    """
    df = make_candles(ENTRY_TIME, [
        # Candle 0: price below stop level — close becomes prev_close
        (1,   1.10100,  1.10160,  1.10080,  1.10150),  # close=1.10150 < 1.10200
        # Candle 1: crossover — prev_close=1.10150 < stop AND high >= stop
        (2,   1.10160,  1.10210,  1.10140,  1.10200),  # triggers at stop 1.10200
        # Walk candles — rises to TP 1.10400
        (3,   1.10200,  1.10250,  1.10180,  1.10230),
        (4,   1.10230,  1.10420,  1.10210,  1.10400),  # high >= TP 1.10400
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**STOP_BUY))

    assert result["pending_order_triggered"] is True
    assert result["pending_wait_minutes"]    == pytest.approx(2.0, abs=1.0)
    assert result["price_path_captured"]     is True
    assert_outcome(result, "hit_tp")
    assert result["pnl_r"] == pytest.approx(2.0, rel=1e-6)


# ── T7.2: stop_buy candle 0 skipped — no prev_close ──────────────────────────

def test_stop_buy_candle_0_not_triggered(inject_candles):
    """
    EC2: Even if candle 0 high >= stop level, it must NOT trigger.
    prev_close is None on candle 0 → condition is False → skip.

    Without EC2 guard, price already at/above stop level at order time
    would trigger immediately — incorrect for a breakout order.
    """
    df = make_candles(ENTRY_TIME, [
        # Candle 0: high already above stop 1.10200 — but no prev_close to confirm
        (1,   1.10180,  1.10250,  1.10160,  1.10220),  # must NOT trigger
        # Candle 1: prev_close=1.10220 > stop 1.10200 → no crossover (was already above)
        (2,   1.10220,  1.10280,  1.10200,  1.10250),  # no crossover — still no trigger
        # Candle 2: prev_close=1.10250 > stop → no crossover
        (3,   1.10250,  1.10300,  1.10220,  1.10270),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**STOP_BUY))

    assert result["pending_order_triggered"] is False
    assert result["price_path_captured"]     is False


# ── T7.3: stop_buy no crossover — price always above level ────────────────────

def test_stop_buy_no_crossover_no_trigger(inject_candles):
    """
    EC2: Price was above stop level from candle 0.
    prev_close is always >= stop level — crossover condition never satisfied.
    No trigger even though price is always above stop.

    This is the key difference from limit_buy — stop_buy REQUIRES confirmed
    crossover from below, not just price being above the level.
    """
    df = make_candles(ENTRY_TIME, [
        (1,  1.10250,  1.10300,  1.10220,  1.10260),  # already above stop
        (2,  1.10260,  1.10310,  1.10230,  1.10270),  # prev_close=1.10260 > stop — no crossover
        (3,  1.10270,  1.10320,  1.10240,  1.10280),  # same
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**STOP_BUY))

    assert result["pending_order_triggered"] is False
    assert result["price_path_captured"]     is False


# ── T7.4: stop_buy never triggers — price never reaches level ─────────────────

def test_stop_buy_never_triggers(inject_candles):
    """
    Price stays below stop level throughout. Order never filled.
    price_path_captured=False, no crash.
    """
    df = make_candles(ENTRY_TIME, [
        (1,  1.10050,  1.10100,  1.10020,  1.10080),  # all below stop 1.10200
        (2,  1.10080,  1.10130,  1.10050,  1.10110),
        (3,  1.10110,  1.10160,  1.10080,  1.10140),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**STOP_BUY))

    assert result["pending_order_triggered"] is False
    assert result["price_path_captured"]     is False
    assert result["pnl_r"]                   is None


# ── T7.5: stop_sell triggers on confirmed crossover ───────────────────────────

def test_stop_sell_triggers_on_crossover(inject_candles):
    """
    prev_close=1.09850 > stop 1.09800, then low=1.09790 <= 1.09800.
    Confirmed breakdown crossover → triggers. Trade hits TP.
    """
    df = make_candles(ENTRY_TIME, [
        # Candle 0: close=1.09850 > stop 1.09800 → becomes prev_close
        (1,   1.09900,  1.09930,  1.09820,  1.09850),  # close=1.09850 > stop
        # Candle 1: crossover — prev_close=1.09850 > stop AND low <= stop
        (2,   1.09840,  1.09860,  1.09790,  1.09810),  # low=1.09790 <= 1.09800 → trigger
        # Walk: falls to TP 1.09600
        (3,   1.09810,  1.09820,  1.09650,  1.09700),
        (4,   1.09700,  1.09710,  1.09580,  1.09600),  # low <= TP 1.09600
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**STOP_SELL))

    assert result["pending_order_triggered"] is True
    assert result["pending_wait_minutes"]    == pytest.approx(2.0, abs=1.0)
    assert result["price_path_captured"]     is True
    assert_outcome(result, "hit_tp")
    assert result["pnl_r"] == pytest.approx(2.0, rel=1e-6)


# ── T7.6: stop_sell candle 0 skipped ─────────────────────────────────────────

def test_stop_sell_candle_0_not_triggered(inject_candles):
    """
    EC2: Even if candle 0 low <= stop level, must NOT trigger.
    prev_close is None → condition False → skip.
    """
    df = make_candles(ENTRY_TIME, [
        # Candle 0: low already below stop 1.09800 — no prev_close to confirm
        (1,   1.09820,  1.09840,  1.09750,  1.09780),  # must NOT trigger
        # Candle 1: prev_close=1.09780 < stop — no crossover (was already below)
        (2,   1.09780,  1.09800,  1.09740,  1.09770),
        (3,   1.09770,  1.09790,  1.09720,  1.09760),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**STOP_SELL))

    assert result["pending_order_triggered"] is False
    assert result["price_path_captured"]     is False


# ── T7.7: stop_sell never triggers ───────────────────────────────────────────

def test_stop_sell_never_triggers(inject_candles):
    """
    Price stays above stop level throughout. Order never filled.
    price_path_captured=False, no crash.
    """
    df = make_candles(ENTRY_TIME, [
        (1,  1.09900,  1.09950,  1.09850,  1.09920),  # all above stop 1.09800
        (2,  1.09920,  1.09970,  1.09880,  1.09940),
        (3,  1.09940,  1.09990,  1.09900,  1.09960),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**STOP_SELL))

    assert result["pending_order_triggered"] is False
    assert result["price_path_captured"]     is False
    assert result["pnl_r"]                   is None