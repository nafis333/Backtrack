"""
tests/test_02_sell.py
---------------------
Sell trade outcomes and direction-specific logic.

Covers
------
S5.1  Sell TP hit
S5.2  Sell SL hit
S5.3  Sell dip direction — adverse move is ABOVE entry (EC11 / P11)
S5.4  Sell MAE direction — MAE measured above entry for sells
S5.5  Clean sell — no dip when price drops straight to TP

Key invariant guarded (EC11 / P11 from Architecture):
  BUY:  adverse = price BELOW entry → dip/MAE measured downward
  SELL: adverse = price ABOVE entry → dip/MAE measured upward
  A sell that moves DOWN is favourable. UP is adverse.

Sell defaults used in this file:
  entry=1.10000, SL=1.10100 (10 pip above = 1R), TP=1.09800 (20 pip below = 2R)
"""

import pytest
from tests.helpers import (
    make_candles, trade_params, assert_outcome, assert_checkpoint,
    ENTRY_TIME, mfe_calculator,
)

# Sell-specific defaults — applied in every test via trade_params(**SELL)
SELL = dict(
    trade_type="sell",
    entry_price=1.10000,
    stoploss_price=1.10100,    # 10 pip ABOVE entry = 1R for a sell
    takeprofit_price=1.09800,  # 20 pip BELOW entry = 2R
)


# ── T2.1: Clean sell TP hit ────────────────────────────────────────────────────

def test_sell_hits_tp(inject_candles):
    """
    Price falls cleanly to TP. High stays below entry — zero adverse move.
    Asserts: outcome='hit_tp', pnl_r=+2.0, exit_price=TP, no dip, mae≈0.
    """
    df = make_candles(ENTRY_TIME, [
        # offset  open      high      low       close
        # High 1.09990 < entry 1.10000 — nothing adverse above entry
        (1,       1.09980,  1.09990,  1.09780,  1.09800),  # low <= TP 1.09800
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**SELL))

    assert_outcome(result, "hit_tp")
    assert result["pnl_r"]         == pytest.approx(2.0,     rel=1e-6)
    assert result["tp_rr_target"]   == pytest.approx(2.0,     rel=1e-6)
    assert result["exit_price"]     == pytest.approx(1.09800, rel=1e-6)
    assert result["tp_was_reached"] is True
    assert result["dip_occurred"]   is False
    assert result["mae_r"]          == pytest.approx(0.0, abs=0.01)


# ── T2.2: Clean sell SL hit ───────────────────────────────────────────────────

def test_sell_hits_sl(inject_candles):
    """
    Price rises immediately to SL. No downward (favourable) move at all.
    Asserts: outcome='hit_sl', pnl_r=-1.0, exit_price=SL.
    UNTP stops same candle as SL hit.
    """
    df = make_candles(ENTRY_TIME, [
        # offset  open      high      low       close
        (1,       1.10050,  1.10120,  1.10020,  1.10100),  # high >= SL 1.10100
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**SELL))

    assert_outcome(result, "hit_sl")
    assert result["pnl_r"]               == pytest.approx(-1.0,    rel=1e-6)
    assert result["exit_price"]          == pytest.approx(1.10100,  rel=1e-6)
    assert result["tp_was_reached"]      is False
    assert result["breakeven_triggered"] is False
    assert result["alive_at_30min"]      is False
    assert_checkpoint(result, "30min", alive=False, outcome="hit_sl")


# ── T2.3: Sell dip direction — adverse is ABOVE entry (EC11) ──────────────────

def test_sell_dip_is_above_entry(inject_candles):
    """
    S5.1: Price moves ABOVE entry before falling to TP.
    For a sell, upward movement is adverse — this IS the dip.
    Asserts: dip_occurred=True, dip_pips>0.

    EC11 regression guard: if the code measured dip as price BELOW entry
    (buy direction), it would see no dip here and return dip_occurred=False.
    """
    df = make_candles(ENTRY_TIME, [
        # Candle 1: high goes 5 pip ABOVE entry (adverse for sell) then comes back
        # offset  open      high      low       close
        (1,       1.10010,  1.10050,  1.09980,  1.10000),  # high=1.10050 → 5 pip above entry
        # Candle 2: falls to TP
        (2,       1.09990,  1.10000,  1.09780,  1.09800),  # low <= TP 1.09800
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**SELL))

    assert_outcome(result, "hit_tp")
    assert result["dip_occurred"] is True
    assert result["dip_pips"]     == pytest.approx(5.0, abs=0.5)  # 5 pip above entry


# ── T2.4: Sell MAE measured above entry (EC11) ────────────────────────────────

def test_sell_mae_measured_above_entry(inject_candles):
    """
    S5.2: For a sell, MAE = adverse move = price going ABOVE entry.
    Same candle setup as T2.3.
    Asserts: mae_r > 0 (adverse move counted correctly).

    EC11 regression guard: if MAE were measured as price BELOW entry
    (buy direction), mae_r would be ≈0 here despite a real adverse move.
    """
    df = make_candles(ENTRY_TIME, [
        # Candle 1: 5 pip adverse move above entry
        (1,       1.10010,  1.10050,  1.09980,  1.10000),
        # Candle 2: falls to TP
        (2,       1.09990,  1.10000,  1.09780,  1.09800),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**SELL))

    assert_outcome(result, "hit_tp")
    # 5 pip adverse / 10 pip SL = 0.5R MAE
    assert result["mae_r"] == pytest.approx(0.5, abs=0.05)
    assert result["mae_r"] > 0.0  # must be positive — adverse move above entry


# ── T2.5: No dip when sell drops straight to TP ───────────────────────────────

def test_sell_no_dip_when_clean_drop(inject_candles):
    """
    Price drops immediately to TP with no upward wick above entry.
    Asserts: dip_occurred=False, mae_r≈0.

    Confirms the direction guard works in both directions — a clean sell
    should have zero dip just like a clean buy (T1.1).
    """
    df = make_candles(ENTRY_TIME, [
        # High 1.09990 < entry 1.10000 — strictly below entry the whole time
        (1,       1.09980,  1.09990,  1.09780,  1.09800),  # low <= TP 1.09800
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**SELL))

    assert_outcome(result, "hit_tp")
    assert result["dip_occurred"] is False
    assert result["dip_pips"]     is None
    assert result["mae_r"]        == pytest.approx(0.0, abs=0.01)