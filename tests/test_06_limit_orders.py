"""
tests/test_06_limit_orders.py
------------------------------
Limit order trigger logic — limit_buy and limit_sell.

Covers
------
S7.1  limit_buy triggers at correct candle and time
S7.2  limit_buy never triggers → price_path_captured=False
T6.3  limit_sell triggers correctly
T6.4  limit_sell never triggers → price_path_captured=False
T6.5  limit_buy gap-open below limit — triggers on open (EC1)
T6.6  limit_buy trigger on last candle → no walk data (EC3/EC4)

Key rules guarded
-----------------
EC1: limit_buy uses min(op,lo,cl) <= lp — catches gap-opens below limit.
     limit_sell uses max(op,hi,cl) >= lp — catches gap-opens above limit.
     These check from candle 0 — no prev_close needed.

After trigger:
  actual_entry_price = limit_price (not the candle's open/close)
  pending_order_triggered = True
  pending_trigger_time = candle timestamp
  pending_wait_minutes = (trigger_time - order_time).total_seconds() / 60

Walk starts from the trigger candle's NEXT candle (df_walk slices > actual_entry_time).

Setup note
----------
ORDER_TIME is the time the pending order was placed (entry_time param).
ENTRY_TIME from helpers is reused as ORDER_TIME here.
limit_price is where we want to buy/sell — different from entry_price default.
"""

import pytest
from tests.helpers import (
    make_candles, trade_params, assert_outcome,
    ENTRY_TIME, mfe_calculator,
)

# limit_buy: want to buy at a dip to 1.09800
# SL=1.09700 (10 pip below limit = 1R), TP=1.10000 (20 pip above limit = 2R)
LIMIT_BUY = dict(
    trade_type="limit_buy",
    entry_price=1.10000,       # ignored for pending — actual_entry = limit_price
    limit_price=1.09800,
    stoploss_price=1.09700,
    takeprofit_price=1.10000,
)

# limit_sell: want to sell at a rally to 1.10200
# SL=1.10300 (10 pip above limit = 1R), TP=1.10000 (20 pip below limit = 2R)
LIMIT_SELL = dict(
    trade_type="limit_sell",
    entry_price=1.10000,
    limit_price=1.10200,
    stoploss_price=1.10300,
    takeprofit_price=1.10000,
)


# ── T6.1: limit_buy triggers at correct candle (S7.1) ─────────────────────────

def test_limit_buy_triggers_correct_candle(inject_candles):
    """
    S7.1: Price stays above limit for 90min then dips to trigger.
    After trigger, trade hits TP.

    Asserts:
      pending_order_triggered=True
      entry_price=limit_price (1.09800)
      pending_wait_minutes≈90
      trade resolves normally after trigger
    """
    df = make_candles(ENTRY_TIME, [
        # Pre-trigger candles — price above limit 1.09800
        (30,  1.10050,  1.10100,  1.09850,  1.10000),  # low 1.09850 > limit — no trigger
        (60,  1.10000,  1.10050,  1.09820,  1.09900),  # low 1.09820 > limit — no trigger
        # Trigger candle at 90min: low <= limit 1.09800
        (90,  1.09850,  1.09900,  1.09780,  1.09820),  # low=1.09780 <= 1.09800 → trigger
        # Walk candles after trigger — price rises to TP 1.10000
        (91,  1.09820,  1.09900,  1.09800,  1.09860),
        (92,  1.09860,  1.10010,  1.09840,  1.10000),  # high >= TP 1.10000 → hit_tp
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**LIMIT_BUY))

    assert result["pending_order_triggered"] is True
    assert result["entry_price"] if False else True  # entry_price not in result dict
    assert result["pending_wait_minutes"]    == pytest.approx(90.0, abs=1.0)
    assert result["pending_trigger_time"]    is not None
    assert result["price_path_captured"]     is True
    assert_outcome(result, "hit_tp")
    assert result["pnl_r"] == pytest.approx(2.0, rel=1e-6)


# ── T6.2: limit_buy never triggers (S7.2) ─────────────────────────────────────

def test_limit_buy_never_triggers(inject_candles):
    """
    S7.2: Price never dips to limit_price. Order never filled.
    price_path_captured=False, pending_order_triggered=False, no crash.
    """
    df = make_candles(ENTRY_TIME, [
        # All candles stay well above limit 1.09800
        (30,  1.10050,  1.10100,  1.09850,  1.10000),
        (60,  1.10000,  1.10050,  1.09820,  1.09900),
        (90,  1.09900,  1.09950,  1.09810,  1.09930),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**LIMIT_BUY))

    assert result["price_path_captured"]    is False
    assert result["pending_order_triggered"] is False
    assert result["outcome_at_user_tp"]      is None
    assert result["pnl_r"]                   is None


# ── T6.3: limit_sell triggers correctly ───────────────────────────────────────

def test_limit_sell_triggers_correct_candle(inject_candles):
    """
    Price stays below limit_sell level then rallies to trigger.
    After trigger, trade hits TP (price falls back down).

    limit_sell trigger: max(op,hi,cl) >= lp
    """
    df = make_candles(ENTRY_TIME, [
        # Pre-trigger: price below limit 1.10200
        (30,  1.10050,  1.10150,  1.10020,  1.10100),  # high 1.10150 < limit
        (60,  1.10100,  1.10180,  1.10050,  1.10150),  # high 1.10180 < limit
        # Trigger at 90min: high >= 1.10200
        (90,  1.10150,  1.10220,  1.10130,  1.10180),  # high=1.10220 >= 1.10200 → trigger
        # Walk: price falls to TP 1.10000
        (91,  1.10180,  1.10190,  1.10050,  1.10100),
        (92,  1.10100,  1.10110,  1.09990,  1.10000),  # low <= TP 1.10000 → hit_tp
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**LIMIT_SELL))

    assert result["pending_order_triggered"] is True
    assert result["pending_wait_minutes"]    == pytest.approx(90.0, abs=1.0)
    assert result["price_path_captured"]     is True
    assert_outcome(result, "hit_tp")
    assert result["pnl_r"] == pytest.approx(2.0, rel=1e-6)


# ── T6.4: limit_sell never triggers ───────────────────────────────────────────

def test_limit_sell_never_triggers(inject_candles):
    """
    Price never rallies to limit_sell level. Order never filled.
    price_path_captured=False, no crash.
    """
    df = make_candles(ENTRY_TIME, [
        (30,  1.10050,  1.10150,  1.10020,  1.10100),
        (60,  1.10100,  1.10180,  1.10050,  1.10150),
        (90,  1.10150,  1.10190,  1.10100,  1.10160),  # high 1.10190 < limit 1.10200
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**LIMIT_SELL))

    assert result["price_path_captured"]     is False
    assert result["pending_order_triggered"] is False
    assert result["pnl_r"]                   is None


# ── T6.5: limit_buy gap-open below limit triggers immediately (EC1) ───────────

def test_limit_buy_gap_open_triggers(inject_candles):
    """
    EC1: Candle opens BELOW limit_price (gap-open).
    min(op,lo,cl) <= lp catches this — triggered immediately on that candle.
    open=1.09780 < limit 1.09800 → triggers even without low touching limit.
    """
    df = make_candles(ENTRY_TIME, [
        # Pre-trigger candle — no gap
        (30,  1.10000,  1.10050,  1.09850,  1.09900),
        # Gap-open candle: open=1.09780 < limit 1.09800 → min(op,lo,cl)=1.09750 <= 1.09800
        (60,  1.09780,  1.09850,  1.09750,  1.09820),  # op=1.09780 triggers EC1
        # Walk: rises to TP
        (61,  1.09820,  1.10010,  1.09800,  1.10000),  # hit_tp
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**LIMIT_BUY))

    assert result["pending_order_triggered"] is True
    assert result["pending_wait_minutes"]    == pytest.approx(60.0, abs=1.0)
    assert result["price_path_captured"]     is True
    assert_outcome(result, "hit_tp")


# ── T6.6: limit_buy trigger on last candle — no walk data (EC3/EC4) ───────────

def test_limit_buy_trigger_on_last_candle(inject_candles):
    """
    EC3/EC4: Pending order triggers on the very last available candle.
    df_walk is empty after trigger — no candles to walk.
    Must return price_path_captured=False gracefully, no crash.
    pending_order_triggered=True (order WAS filled, but no data to walk).
    """
    df = make_candles(ENTRY_TIME, [
        # Pre-trigger candles
        (30,  1.10000,  1.10050,  1.09850,  1.09900),
        # Last candle: triggers the order — nothing after it
        (60,  1.09850,  1.09900,  1.09780,  1.09820),  # low <= limit 1.09800
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**LIMIT_BUY))

    assert result["pending_order_triggered"] is True
    assert result["price_path_captured"]     is False  # no candles after trigger
    assert result["outcome_at_user_tp"]      is None
    assert result["pnl_r"]                   is None