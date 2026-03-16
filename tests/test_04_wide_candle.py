"""
tests/test_04_wide_candle.py
----------------------------
Post-walk cleanup — wide candle edge cases.

Covers
------
S2.1  Phantom dip cleared when dip and TP fire on same candle (BUG-4)
S2.2  Phantom BE cleared when BE and TP fire on same candle (BUG-5)
T4.3  Dip preserved when it occurs on a DIFFERENT candle than TP
T4.4  BE preserved when it fires on a DIFFERENT candle than TP

Why these tests exist
---------------------
Candle iteration order: 7c (dip) → 7e (BE) → 7f (TP).
On a wide candle, all three can fire in the same iteration.
Without post-walk cleanup, a trade that spikes straight to TP
would be incorrectly classified as "Dip-then-run" or "had BE active".

Post-walk cleanup rules (from Architecture):
  Dip: if peak_dip_time >= resolution_candle_time → zero all dip fields
  BE:  if outcome='hit_tp' AND be_trigger_min == resolution_min → clear all BE fields

These are permanent regressions guards for BUG-4 and BUG-5.
"""

import pytest
from tests.helpers import (
    make_candles, trade_params, assert_outcome,
    ENTRY_TIME, mfe_calculator,
)

BE_1R = dict(breakeven_active=True, breakeven_type="rr", breakeven_value=1.0)


# ── T4.1: Phantom dip cleared — dip and TP same candle (S2.1 / BUG-4) ─────────

def test_dip_cleared_when_same_candle_as_tp(inject_candles):
    """
    S2.1 / BUG-4 regression guard.

    Single wide candle:
      low=1.09950  → 5 pip adverse wick (step 7c sets dip_occurred=True)
      high=1.10210 → hits TP 1.10200 (step 7f closes trade)

    Both happen in the same iteration. Post-walk cleanup must detect
    peak_dip_time >= resolution_candle_time and zero all dip fields.

    Without the fix: dip_occurred=True, dip_pips=5 → wrong "Dip-then-run".
    With the fix:    dip_occurred=False, dip_pips=None.
    """
    df = make_candles(ENTRY_TIME, [
        # Single wide candle: adverse wick down AND TP hit up
        # offset  open      high      low       close
        (1,       1.10010,  1.10210,  1.09950,  1.10200),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert_outcome(result, "hit_tp")
    assert result["dip_occurred"]   is False   # ← post-walk cleanup fired
    assert result["dip_pips"]       is None    # ← zeroed, not 5.0
    assert result["dip_time_minutes"] is None


# ── T4.2: Phantom BE cleared — BE and TP same candle (S2.2 / BUG-5) ───────────

def test_be_cleared_when_same_candle_as_tp(inject_candles):
    """
    S2.2 / BUG-5 regression guard.

    Single wide candle:
      high=1.10210 → crosses BE trigger (~1.10100, step 7e) AND TP 1.10200 (step 7f)

    be_trigger_min == resolution_min → phantom BE.
    Post-walk cleanup must clear all BE fields.

    Without the fix: breakeven_triggered=True → wrong "BE trade".
    With the fix:    breakeven_triggered=False, all BE fields None.
    """
    df = make_candles(ENTRY_TIME, [
        # Single wide candle that crosses both BE level and TP
        # offset  open      high      low       close
        (1,       1.10020,  1.10210,  1.10010,  1.10200),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**BE_1R))

    assert_outcome(result, "hit_tp")
    assert result["pnl_r"]                          == pytest.approx(2.0, rel=1e-6)
    assert result["breakeven_triggered"]            is False   # ← post-walk cleanup fired
    assert result["breakeven_sl_price"]             is None
    assert result["breakeven_trigger_time_minutes"] is None
    assert result["mfe_at_breakeven_r"]             is None
    assert result["mfe_after_be_r"]                 is None


# ── T4.3: Dip preserved when on a different candle than TP ────────────────────

def test_dip_preserved_when_different_candle(inject_candles):
    """
    Dip on candle 1, TP on candle 3. peak_dip_time < resolution_candle_time.
    Post-walk cleanup must NOT clear the dip — it was real.
    """
    df = make_candles(ENTRY_TIME, [
        # Candle 1: adverse wick 5 pip below entry (dip fires)
        (1,  1.09990,  1.10010,  1.09950,  1.10000),
        # Candle 2: neutral
        (2,  1.10010,  1.10050,  1.10000,  1.10030),
        # Candle 3: hits TP (different candle from dip)
        (3,  1.10050,  1.10210,  1.10030,  1.10200),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert_outcome(result, "hit_tp")
    assert result["dip_occurred"] is True    # dip was real — must NOT be cleared
    assert result["dip_pips"]     is not None
    assert result["dip_pips"]     > 0.0


# ── T4.4: BE preserved when on a different candle than TP ─────────────────────

def test_be_preserved_when_different_candle(inject_candles):
    """
    BE fires on candle 1 (be_trigger_min=1). TP fires on candle 2 (resolution_min=2).
    be_trigger_min != resolution_min → cleanup does NOT clear BE.
    breakeven_triggered must remain True.
    """
    df = make_candles(ENTRY_TIME, [
        # Candle 1: high crosses BE trigger (~1.10100) but not TP (1.10200)
        (1,  1.10050,  1.10101,  1.10010,  1.10090),  # BE fires (fp-safe: 1.10101)
        # Candle 2: continues to TP
        (2,  1.10090,  1.10210,  1.10050,  1.10200),  # TP fires
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**BE_1R))

    assert_outcome(result, "hit_tp")
    assert result["breakeven_triggered"] is True    # real BE — must NOT be cleared
    assert result["mfe_at_breakeven_r"]  is not None
    assert result["mfe_after_be_r"]      is not None