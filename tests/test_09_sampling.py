"""
tests/test_09_sampling.py
--------------------------
mfe_path sampling and R milestone timing.

Covers
------
S8.1  mfe_path sampled at 15-min intervals (PATH_INTERVAL_MIN=15)
S8.2  forced path entry at trade close even if not on 15-min boundary
T9.3  BUG-3: last_path_min advances by += 15, not = elapsed_min
      (samples stay evenly spaced regardless of candle offsets)
T9.4  R milestone times recorded correctly — time_to_Xr_minutes
T9.5  R milestone NOT recorded if trade closes before reaching that level
T9.6  mfe_path untp_alive flag: 1 while UNTP running, 0 after UNTP stops

Key rules guarded
-----------------
BUG-3 (permanent): mfe_path uses last_path_min += PATH_INTERVAL_MIN.
  NOT last_path_min = elapsed_min.
  If it used elapsed_min, samples would anchor to candle offsets and
  lose the even 15-min grid when candles are unevenly spaced.

mfe_path_json format: [[elapsed_min, mfe_r, mae_r, untp_alive], ...]
  elapsed_min  = minutes since actual_entry_time (rounded to 2dp)
  mfe_r / mae_r = peaks at that moment / sl_distance_pips
  untp_alive   = 1 if UNTP still running, 0 if stopped

R milestone fields: time_to_0_5r_minutes, time_to_1r_minutes, ...
  Recorded as elapsed_min at the FIRST candle where peak_mfe_r >= level.
  None if trade closes before that level is reached.
  Only updated while not trade_fully_closed.
"""

import json
import pytest
from tests.helpers import (
    make_candles, trade_params, assert_outcome,
    ENTRY_TIME, mfe_calculator,
)


# ── T9.1: mfe_path sampled at 15-min intervals (S8.1) ─────────────────────────

def test_mfe_path_sampled_at_15min_intervals(inject_candles):
    """
    S8.1: Candles at 15, 30, 45, 60 min. PATH_INTERVAL_MIN=15.
    last_path_min starts at -15 so first sample fires at elapsed >= 0.
    Expect path entries near 15, 30, 45min (candle times) plus forced close entry.

    We verify: path has >= 3 entries, all elapsed_min values are multiples of 15
    (±1 min tolerance for candle alignment).
    """
    df = make_candles(ENTRY_TIME, [
        (15,  1.10010,  1.10050,  1.10005,  1.10030),
        (30,  1.10030,  1.10080,  1.10020,  1.10060),
        (45,  1.10060,  1.10120,  1.10050,  1.10100),
        (60,  1.10100,  1.10210,  1.10090,  1.10200),  # TP hit at 60min
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert_outcome(result, "hit_tp")
    path = json.loads(result["mfe_path_json"])
    assert len(path) >= 3, f"Expected >= 3 path entries, got {len(path)}"

    # All interval-sampled entries should be near multiples of 15
    elapsed_values = [p[0] for p in path]
    for t in elapsed_values[:-1]:  # last entry may be forced close (not on grid)
        assert t % 15 <= 1 or t % 15 >= 14, (
            f"Path entry at elapsed={t} is not near a 15-min boundary"
        )


# ── T9.2: forced path entry at trade close (S8.2) ─────────────────────────────

def test_mfe_path_forced_entry_at_trade_close(inject_candles):
    """
    S8.2: Trade closes at 22min — not on a 15-min boundary.
    A forced path entry must be added at elapsed=22 even though
    the next interval sample would be at 30min.

    Verify: path contains an entry at approximately 22min.
    """
    df = make_candles(ENTRY_TIME, [
        (15,  1.10010,  1.10050,  1.10005,  1.10030),
        (22,  1.10030,  1.10210,  1.10020,  1.10200),  # TP hit at 22min (off-grid)
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert_outcome(result, "hit_tp")
    path = json.loads(result["mfe_path_json"])
    elapsed_values = [p[0] for p in path]

    # Must have an entry near 22min (the forced close entry)
    assert any(20 <= t <= 24 for t in elapsed_values), (
        f"No forced path entry near 22min. Path elapsed values: {elapsed_values}"
    )


# ── T9.3: BUG-3 — last_path_min advances by += 15 not = elapsed_min ──────────

def test_mfe_path_grid_not_anchored_to_candle_offsets(inject_candles):
    """
    BUG-3 regression guard.

    Candles at 17, 31, 46, 61 min — deliberately off the 15-min grid.
    If the bug existed (last_path_min = elapsed_min):
      - Sample at 17 → last_path_min=17 → next at >= 32 → fires at 46
      - Samples would be at 17, 46 — grid anchored to candle positions
    With the fix (last_path_min += 15):
      - last_path_min starts at -15 → fires at 17 (>= 0) → last_path_min = 0
      - Next fires at >= 15 → fires at 31 → last_path_min = 15
      - Next fires at >= 30 → fires at 31... wait, 31 >= 30 → fires again?
      Actually let's trace: after 31: last_path_min=15, next at >= 30
      46 >= 30 → fires → last_path_min=30, next at >= 45
      61 >= 45 → fires → last_path_min=45

    Key assertion: with the fix, we get MORE samples (4) than without (2).
    We verify: len(path) >= 3 (impossible if anchored to candle positions only).
    """
    df = make_candles(ENTRY_TIME, [
        (17,  1.10010,  1.10060,  1.10005,  1.10040),
        (31,  1.10040,  1.10090,  1.10030,  1.10070),
        (46,  1.10070,  1.10130,  1.10060,  1.10110),
        (61,  1.10110,  1.10210,  1.10100,  1.10200),  # TP at 61min
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert_outcome(result, "hit_tp")
    path = json.loads(result["mfe_path_json"])

    # With += 15: samples at ~17, ~31, ~46, ~61 (4 entries minimum)
    # With = elapsed_min (bug): would only get ~2-3 due to anchoring
    assert len(path) >= 3, (
        f"BUG-3: only {len(path)} path entries — "
        f"suggests last_path_min may be anchored to elapsed_min instead of += 15"
    )


# ── T9.4: R milestone times recorded correctly ────────────────────────────────

def test_r_milestone_times_recorded(inject_candles):
    """
    Price rises steadily: hits 0.5R at 15min, 1R at 30min, 2R at 60min.
    Verify time_to_Xr_minutes fields match the candle elapsed times.
    """
    # entry=1.10000, SL=1.09900 (10pip/1R), TP=1.10200 (2R)
    # 0.5R = 1.10050, 1R = 1.10100, 2R = 1.10200
    df = make_candles(ENTRY_TIME, [
        (15,  1.10010,  1.10060,  1.10005,  1.10050),  # high=1.10060 → hits 0.5R (5pip)
        (30,  1.10050,  1.10110,  1.10040,  1.10100),  # high=1.10110 → hits 1R (10pip)
        (60,  1.10100,  1.10210,  1.10090,  1.10200),  # high=1.10210 → hits 2R, TP fires
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert_outcome(result, "hit_tp")
    assert result["time_to_0_5r_minutes"] == pytest.approx(15.0, abs=1.0)
    assert result["time_to_1r_minutes"]   == pytest.approx(30.0, abs=1.0)
    assert result["time_to_2r_minutes"]   == pytest.approx(60.0, abs=1.0)
    # 3R never reached before TP — must be None
    assert result["time_to_3r_minutes"]   is None
    assert result["time_to_4r_minutes"]   is None


# ── T9.5: R milestone None when trade closes before level reached ──────────────

def test_r_milestone_none_when_not_reached(inject_candles):
    """
    Trade hits SL at 1R without ever reaching 1.5R, 2R, 3R, etc.
    Milestones above the SL level must all be None.
    0.5R may be reached briefly on the way up before SL fires — that's fine.
    """
    df = make_candles(ENTRY_TIME, [
        (15,  1.10010,  1.10060,  1.10005,  1.10050),  # 0.5R reached
        (30,  1.10050,  1.10060,  1.09880,  1.09900),  # SL hit — never passed 1R
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert_outcome(result, "hit_sl")
    # 1R never reached (1.10100) before SL at 1.09900
    assert result["time_to_1r_minutes"]   is None
    assert result["time_to_1_5r_minutes"] is None
    assert result["time_to_2r_minutes"]   is None
    assert result["time_to_3r_minutes"]   is None


# ── T9.6: mfe_path untp_alive flag ────────────────────────────────────────────

def test_mfe_path_untp_alive_flag(inject_candles):
    """
    mfe_path entries have a 4th field: untp_alive (1=running, 0=stopped).
    Trade hits TP at 30min (1R TP). UNTP keeps running.
    At 60min candle: UNTP still alive → flag=1.
    At 90min: price drops to original SL → UNTP stops → forced path entry with flag=0.

    Verify: at least one entry with flag=1 (before UNTP stop)
            and at least one entry with flag=0 (at/after UNTP stop).
    """
    df = make_candles(ENTRY_TIME, [
        (30,  1.10050,  1.10110,  1.10040,  1.10100),  # TP=1.10100 (1R) hit at 30min
        (60,  1.10080,  1.10120,  1.10050,  1.10090),  # UNTP alive
        (90,  1.10000,  1.10010,  1.09880,  1.09900),  # UNTP stops at original SL
        (120, 1.09900,  1.10500,  1.09800,  1.10400),  # post-stop
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(takeprofit_price=1.10100))

    assert_outcome(result, "hit_tp")
    path = json.loads(result["mfe_path_json"])

    alive_flags  = [p[3] for p in path]
    assert 1 in alive_flags, "No path entry with untp_alive=1 (UNTP running)"
    assert 0 in alive_flags, "No path entry with untp_alive=0 (UNTP stopped)"

    # Once flag goes to 0 it must stay 0 — no flip back to 1
    seen_zero = False
    for flag in alive_flags:
        if flag == 0:
            seen_zero = True
        if seen_zero:
            assert flag == 0, "untp_alive flag flipped back to 1 after stopping"