"""
tests/test_03_breakeven.py
--------------------------
Breakeven logic — all variants and edge cases.

Covers
------
S1.3  BE triggers then price retraces to entry → hit_be
T3.2  BE triggers then TP fires → hit_tp with be_triggered=True
S3.3  BE configured but TP fires first (below BE level) → be_triggered=False (EC10/EC12)
T3.4  BE inactive — entry retrace resolves as hit_sl, not hit_be
T3.5  BE type='pips' — trigger price computed from pip value
T3.6  Sell BE — symmetric direction

Floating-point pitfall (critical for test candle design)
---------------------------------------------------------
be_trigger_price for EURUSD 1R:
  sl_distance_pips = 10.0, initial_risk = 10 * 0.0001 = 0.001
  be_trigger_price = 1.10000 + 0.001 = 1.1010000000000002  (float imprecision)
  So high=1.10100 (== 1.101) FAILS the >= check: 1.101 >= 1.1010000000000002 is False.
  Use high=1.10101 (one extra pip) to guarantee the trigger fires.

Same issue for sell: be_trigger_sell = 1.0990000000000002, so use lo=1.09899.
For pips=8: be_trigger = 1.10000 + 8*0.0001 = 1.10080. Use high=1.10090.
"""

import pytest
from tests.helpers import (
    make_candles, trade_params, assert_outcome, assert_checkpoint,
    ENTRY_TIME, mfe_calculator,
)

BE_1R = dict(breakeven_active=True, breakeven_type="rr", breakeven_value=1.0)


# ── T3.1: BE triggers then price retraces to entry (S1.3) ─────────────────────

def test_be_triggers_then_retraces(inject_candles):
    """
    S1.3: Candle 1 high=1.10101 > be_trigger 1.10100+fp → BE fires.
    Candle 2 low=1.09990 <= entry 1.10000 (new SL) → hit_be.
    """
    df = make_candles(ENTRY_TIME, [
        # offset  open      high      low       close
        (1,       1.10050,  1.10101,  1.10010,  1.10090),  # 1.10101 > be_trigger (fp-safe)
        (2,       1.10080,  1.10090,  1.09990,  1.10010),  # low <= entry → hit_be
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**BE_1R))

    assert_outcome(result, "hit_be")
    assert result["pnl_r"]                          == pytest.approx(0.0,     abs=1e-9)
    assert result["exit_price"]                     == pytest.approx(1.10000, rel=1e-6)
    assert result["breakeven_triggered"]            is True
    assert result["breakeven_sl_price"]             == pytest.approx(1.10000, rel=1e-6)
    assert result["mfe_at_breakeven_r"]             == pytest.approx(1.01,    abs=0.02)
    assert result["breakeven_trigger_time_minutes"] is not None
    assert result["alive_at_30min"] is False
    assert_checkpoint(result, "30min", alive=False, outcome="hit_be")


# ── T3.2: BE triggers then TP fires ───────────────────────────────────────────

def test_be_triggers_then_tp_fires(inject_candles):
    """
    Candle 1 triggers BE (high=1.10101). Candle 2 continues to TP.
    be_triggered=True AND outcome=hit_tp can coexist.
    mfe_after_be_r > 0: price gained more R after BE fired.
    """
    df = make_candles(ENTRY_TIME, [
        (1,  1.10050,  1.10101,  1.10010,  1.10090),  # BE fires
        (2,  1.10090,  1.10220,  1.10050,  1.10200),  # TP fires
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**BE_1R))

    assert_outcome(result, "hit_tp")
    assert result["pnl_r"]               == pytest.approx(2.0, rel=1e-6)
    assert result["breakeven_triggered"] is True
    assert result["mfe_at_breakeven_r"]  is not None
    assert result["mfe_at_breakeven_r"]  > 0.0
    assert result["mfe_after_be_r"]      is not None
    assert result["mfe_after_be_r"]      > 0.0


# ── T3.3: BE configured but TP fires first — be_triggered=False (S3.3/EC12) ───

def test_be_configured_tp_fires_before_be_level(inject_candles):
    """
    S3.3 / EC12: TP=0.5R (1.10050), BE at 1R (trigger ~1.10100).
    High=1.10060 >= TP but < BE trigger → TP fires, BE never reached.
    be_triggered must stay False.
    """
    df = make_candles(ENTRY_TIME, [
        (1,  1.10020,  1.10060,  1.10010,  1.10050),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(
        takeprofit_price=1.10050,
        **BE_1R,
    ))

    assert_outcome(result, "hit_tp")
    assert result["breakeven_triggered"]            is False
    assert result["breakeven_sl_price"]             is None
    assert result["breakeven_trigger_time_minutes"] is None
    assert result["mfe_at_breakeven_r"]             is None
    assert result["mfe_after_be_r"]                 is None


# ── T3.4: BE inactive — entry retrace is hit_sl not hit_be ────────────────────

def test_be_inactive_entry_retrace_is_not_hit_be(inject_candles):
    """
    BE not configured. Price rises then retraces through original SL.
    Must resolve as hit_sl — hit_be only fires when BE was armed.
    """
    df = make_candles(ENTRY_TIME, [
        (1,  1.10050,  1.10101,  1.10010,  1.10090),
        (2,  1.10080,  1.10090,  1.09880,  1.09900),  # drops to SL 1.09900
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(breakeven_active=False))

    assert_outcome(result, "hit_sl")
    assert result["pnl_r"]               == pytest.approx(-1.0, rel=1e-6)
    assert result["breakeven_triggered"] is False


# ── T3.5: BE type='pips' ──────────────────────────────────────────────────────

def test_be_pips_type_trigger(inject_candles):
    """
    BE type='pips', value=8.0.
    be_trigger_price = 1.10000 + 8*0.0001 = 1.10080.
    Candle 1 high=1.10090 >= 1.10080 → BE fires.
    Candle 2 low=1.09990 <= entry 1.10000 (new SL) → hit_be.
    takeprofit_price=None to avoid 'open' outcome.
    """
    df = make_candles(ENTRY_TIME, [
        (1,  1.10050,  1.10090,  1.10010,  1.10070),  # high >= be_trigger 1.10080
        (2,  1.10060,  1.10070,  1.09990,  1.10000),  # low <= entry → hit_be
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(
        takeprofit_price=None,
        breakeven_active=True,
        breakeven_type="pips",
        breakeven_value=8.0,
    ))

    assert_outcome(result, "hit_be")
    assert result["pnl_r"]               == pytest.approx(0.0, abs=1e-9)
    assert result["breakeven_triggered"] is True
    assert result["exit_price"]          == pytest.approx(1.10000, rel=1e-6)


# ── T3.6: Sell BE — symmetric direction ───────────────────────────────────────

def test_sell_be_triggers_then_retraces(inject_candles):
    """
    Sell: entry=1.10000, SL=1.10100 (10 pip above = 1R), TP=1.09800.
    be_trigger_sell = 1.0990000000000002 (fp). Use lo=1.09899 to guarantee trigger.
    Candle 2 hi=1.10010 >= entry 1.10000 (new SL for sell) → hit_be.
    """
    df = make_candles(ENTRY_TIME, [
        # offset  open      high      low       close
        (1,       1.09970,  1.09990,  1.09899,  1.09910),  # lo=1.09899 < be_trigger (fp-safe)
        (2,       1.09920,  1.10010,  1.09910,  1.09990),  # high >= entry → hit_be
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(
        trade_type="sell",
        entry_price=1.10000,
        stoploss_price=1.10100,
        takeprofit_price=1.09800,
        **BE_1R,
    ))

    assert_outcome(result, "hit_be")
    assert result["pnl_r"]               == pytest.approx(0.0,     abs=1e-9)
    assert result["exit_price"]          == pytest.approx(1.10000, rel=1e-6)
    assert result["breakeven_triggered"] is True
    assert result["mfe_at_breakeven_r"]  is not None
    assert result["mfe_at_breakeven_r"]  > 0.0