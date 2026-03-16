"""
tests/test_05_untp.py
---------------------
UNTP walk behaviour — continuation, stop conditions, freeze semantics.

Covers
------
S3.1  UNTP continues after TP hit, then stops at original SL
S3.2  UNTP stops at entry retrace when BE was triggered
S3.3  UNTP does NOT stop at entry retrace when BE was never triggered (EC10)
T5.4  hit_sl trade — UNTP stops same candle as SL (alive=False immediately)
T5.5  mfe_at_Xh_r frozen after UNTP stops — later candles cannot inflate it (EC16)
T5.6  outcome_at_Xh reflects TRADE outcome, alive_at_Xh reflects UNTP status (independent)

Key rules guarded
-----------------
EC10: UNTP stop = entry retrace ONLY if be_triggered=True (actual, not configured).
EC16: When UNTP stops, all remaining snapshots backfilled immediately with frozen
      peaks. Later candle movement cannot inflate mfe_at_Xh_r.
Architecture: outcome_at_Xh and alive_at_Xh are independent fields.
  A trade can be outcome='hit_tp' AND alive_at_Xh=True simultaneously.

Checkpoint minutes used: 30=30min, 60=1h, 120=2h
Candle offsets used go up to ~200 min to cover 1h and 2h checkpoints.
"""

import pytest
from tests.helpers import (
    make_candles, trade_params, assert_outcome, assert_checkpoint,
    ENTRY_TIME, mfe_calculator,
)

BE_1R = dict(breakeven_active=True, breakeven_type="rr", breakeven_value=1.0)


# ── T5.1: UNTP continues after TP, then stops at original SL (S3.1) ───────────

def test_untp_continues_after_tp_hits_original_sl(inject_candles):
    """
    S3.1: Trade hits TP at ~45min. UNTP keeps running.
    At 1h checkpoint (60min): trade already closed (outcome_at_1h='hit_tp'),
    but UNTP still alive (alive_at_1h=True — SL not yet hit at 60min).
    After ~90min: price drops to original SL → UNTP stops.
    At 2h checkpoint (120min): alive_at_2h=False, mfe frozen.

    Uses TP=1R so UNTP has room to continue before hitting SL at entry-10pip.
    """
    df = make_candles(ENTRY_TIME, [
        # Candles 1-45: rise to TP 1.10100 (1R)
        (45,  1.10050,  1.10110,  1.10010,  1.10100),  # TP hit at 45min
        # Candle at 65min: UNTP alive, price drifts
        (65,  1.10080,  1.10120,  1.10050,  1.10090),  # UNTP still running at 1h checkpoint
        # Candle at 95min: price drops to original SL 1.09900 → UNTP stops
        (95,  1.10000,  1.10010,  1.09880,  1.09900),  # lo <= original SL
        # Candle at 130min: after UNTP stop — mfe should be frozen
        (130, 1.09900,  1.10500,  1.09800,  1.10200),  # big candle — must NOT inflate mfe
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(takeprofit_price=1.10100))

    assert_outcome(result, "hit_tp")
    # At 1h (60min): trade closed, UNTP still alive
    assert_checkpoint(result, "1h", alive=True, outcome="hit_tp")
    # At 2h (120min): UNTP stopped (SL hit at ~95min)
    assert_checkpoint(result, "2h", alive=False, outcome="hit_tp")


# ── T5.2: UNTP stops at entry retrace when BE triggered (S3.2) ────────────────

def test_untp_stops_at_entry_retrace_when_be_triggered(inject_candles):
    """
    S3.2: BE fires at 1R, then trade hits TP. After TP close, UNTP continues.
    Price retraces to entry (1.10000) → UNTP stops (be_triggered=True → entry retrace = stop).
    UNTP must NOT continue past entry retrace.
    """
    df = make_candles(ENTRY_TIME, [
        # Candle 1: BE fires (high > be_trigger ~1.10100)
        (1,   1.10050,  1.10101,  1.10010,  1.10090),
        # Candle 2: TP hit at 1.10200
        (2,   1.10090,  1.10210,  1.10050,  1.10200),
        # Candle at 65min: UNTP continues post-TP, still above entry
        (65,  1.10150,  1.10180,  1.10110,  1.10160),
        # Candle at 95min: retraces to entry 1.10000 → UNTP stops
        (95,  1.10100,  1.10110,  1.09990,  1.10000),  # lo <= entry
        # Candle at 130min: after UNTP stop — must not update snapshots
        (130, 1.09900,  1.10600,  1.09800,  1.10500),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(**BE_1R))

    assert_outcome(result, "hit_tp")
    assert result["breakeven_triggered"] is True
    # At 1h: UNTP still alive (entry retrace not yet hit)
    assert_checkpoint(result, "1h", alive=True, outcome="hit_tp")
    # At 2h: UNTP stopped at entry retrace (~95min)
    assert_checkpoint(result, "2h", alive=False, outcome="hit_tp")


# ── T5.3: UNTP does NOT stop at entry retrace when BE not triggered (EC10/S3.3) ─

def test_untp_not_stopped_by_entry_when_be_not_triggered(inject_candles):
    """
    S3.3 / EC10 regression guard.

    BE configured at 1R but TP=0.5R fires first — BE never triggered.
    After TP close, price retraces through entry (1.10000).
    UNTP must remain alive at entry retrace because be_triggered=False.
    UNTP only stops at original SL (1.09900).

    If the code incorrectly uses be_trigger_price config instead of
    be_triggered actual state, UNTP would stop at entry — wrong.
    """
    df = make_candles(ENTRY_TIME, [
        # Candle 1: TP=0.5R (1.10050) fires before BE level (1.10100)
        (1,   1.10020,  1.10060,  1.10010,  1.10050),  # TP hit
        # Candle at 65min: price drops through entry — UNTP must stay alive
        (65,  1.10000,  1.10010,  1.09910,  1.09950),  # lo below entry but above SL
        # Candle at 130min: still alive (SL not yet hit)
        (130, 1.09950,  1.10000,  1.09920,  1.09960),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(
        takeprofit_price=1.10050,  # 0.5R — fires before BE level
        **BE_1R,
    ))

    assert_outcome(result, "hit_tp")
    assert result["breakeven_triggered"] is False
    # At 1h: UNTP still alive — entry retrace did NOT stop it
    assert_checkpoint(result, "1h", alive=True, outcome="hit_tp")
    # At 2h: still alive (SL at 1.09900 not hit yet)
    assert_checkpoint(result, "2h", alive=True, outcome="hit_tp")


# ── T5.4: hit_sl — UNTP stops same candle as SL ───────────────────────────────

def test_untp_stops_same_candle_as_sl(inject_candles):
    """
    SL hit resolves trade AND stops UNTP on the same candle.
    SL = UNTP stop condition when be_triggered=False.
    All checkpoints must have alive=False immediately.
    """
    df = make_candles(ENTRY_TIME, [
        (1,  1.09980,  1.10010,  1.09880,  1.09900),  # lo <= SL 1.09900
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert_outcome(result, "hit_sl")
    assert result["alive_at_30min"] is False
    assert result["alive_at_1h"]    is False
    assert result["alive_at_2h"]    is False
    assert_checkpoint(result, "30min", alive=False, outcome="hit_sl")


# ── T5.5: mfe_at_Xh_r frozen after UNTP stops (EC16) ─────────────────────────

def test_untp_mfe_frozen_after_stop(inject_candles):
    """
    EC16 regression guard.

    UNTP stops at ~35min (SL hit in a hit_tp trade post-close).
    A candle at 130min has a very high price (would inflate mfe if not frozen).
    mfe_at_2h_r must equal mfe_at_1h_r — frozen at stop, not updated by later candles.
    """
    df = make_candles(ENTRY_TIME, [
        # Candle 1: trade hits TP at 1.10100 (1R)
        (1,   1.10050,  1.10110,  1.10010,  1.10100),
        # Candle at 35min: UNTP hits original SL 1.09900 → UNTP stops, mfe frozen
        (35,  1.10000,  1.10010,  1.09880,  1.09900),
        # Candle at 130min: massive spike — must NOT update any snapshot
        (130, 1.09900,  1.15000,  1.09800,  1.14000),  # would be 500R if not frozen
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(takeprofit_price=1.10100))

    assert_outcome(result, "hit_tp")
    # UNTP stopped at ~35min — all checkpoints alive=False
    assert result["alive_at_1h"]  is False
    assert result["alive_at_2h"]  is False
    # mfe values frozen at stop — must NOT reflect 130min candle spike
    mfe_1h = result["mfe_at_1h_r"]
    mfe_2h = result["mfe_at_2h_r"]
    assert mfe_1h is not None
    assert mfe_2h is not None
    assert mfe_1h == pytest.approx(mfe_2h, rel=1e-6)  # frozen — same at both checkpoints
    assert mfe_1h < 50.0  # must not be the 500R spike from 130min candle


# ── T5.6: outcome_at_Xh and alive_at_Xh are independent (Architecture rule) ───

def test_outcome_and_alive_are_independent(inject_candles):
    """
    outcome_at_Xh = TRADE outcome. alive_at_Xh = UNTP status. They are independent.
    A trade can be outcome='hit_tp' AND alive_at_Xh=True simultaneously.

    Trade closes at 45min (hit_tp). UNTP still running at 1h checkpoint.
    → outcome_at_1h='hit_tp', alive_at_1h=True.
    This combination is valid and expected — must not be confused.
    """
    df = make_candles(ENTRY_TIME, [
        # TP hit at 45min
        (45,  1.10050,  1.10110,  1.10010,  1.10100),
        # Candle at 65min: UNTP alive, no SL hit
        (65,  1.10080,  1.10120,  1.10050,  1.10090),
        # Candle at 130min: UNTP alive, no SL hit
        (130, 1.10050,  1.10100,  1.10020,  1.10070),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(takeprofit_price=1.10100))

    assert_outcome(result, "hit_tp")
    # At 1h: trade already closed (hit_tp) but UNTP still running (SL not hit)
    assert result["outcome_at_1h"] == "hit_tp"  # trade outcome
    assert result["alive_at_1h"]   is True       # UNTP still running
    # At 2h: UNTP still alive (SL at 1.09900 not hit in this data)
    assert result["alive_at_2h"]   is True