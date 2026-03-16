"""
tests/test_14_statistics.py
---------------------------
Converts every scenario in Test_Scenarios.md into executable assertions.

Coverage
--------
Groups 1-5, 7-8  — Already covered by tests 01-13 (mfe_calculator unit +
                    integration). Verified by cross-reference, not re-tested here.

Group 6          — Statistics logic. Fully new. Covered below:
  S6.1  fixed_untp: win = mfe_at_Xh_r >= target (peak MFE, alive irrelevant)
  S6.2  hit_be = loss in original_tp mode win rate (NOT in streak)
  S6.3  net_rr = sum of pnl_r only (not derived from MFE or prices)

Additional scenarios added beyond Test_Scenarios.md
----------------------------------------------------
  S6.4  resolve_win_loss: every outcome × original_tp mode
  S6.5  resolve_win_loss: fixed_tp (trade walk peak) with no time limit
  S6.6  compute_fixed_untp_overview: UNTP peak MFE vs target; alive irrelevant
  S6.7  resolve_win_loss: fixed_tp with unit='pips' — converts pip target to R per-trade
  S6.8  resolve_win_loss: price_path_captured=False excluded before calling
  S6.9  compute_overview: excluded trades never in numerator or denominator
  S6.10 compute_overview: equity curve is cumulative
  S6.11 compute_overview: drawdown curve max_drawdown correct
  S6.12 compute_overview: win/loss streaks — inconclusive does not break streak
  S6.13 compute_overview: open/none are inconclusive in original_tp mode
  S6.14 compute_overview: avg_win_r / avg_loss_r
  S6.15 compute_overview: outcome_breakdown counts

Mode name mapping (DECISION-15):
  OLD (retired)  → NEW
  fixed_rr       → fixed_tp   (trade walk mfe_r, unit='R')
  fixed_pips     → fixed_tp   with unit='pips'
  fixed_untp     → compute_fixed_untp_overview() (UNTP peak mfe_at_Xh_r vs target;
                   alive_at_Xh irrelevant — peak is frozen at UNTP stop if stopped early)

Module structure
----------------
No mfe_calculator, no parquet, no DB. Pure Python trade dicts only.
No fixtures from conftest are needed (mock_streak / clean_data_frames
apply to mfe_calculator, not trade_statistics).

Trade dict builder
------------------
_t(**fields) builds a minimal trade dict with safe defaults for all fields
that resolve_win_loss / compute_overview / compute_fixed_untp_overview /
compute_untp_stats may touch. Overrides are per-test.
"""

import pytest

# ── Import ─────────────────────────────────────────────────────────────────────
try:
    from utils.trade_statistics import (
        resolve_win_loss, compute_overview, compute_untp_stats, compute_fixed_untp_overview,
    )
except ModuleNotFoundError:
    from trade_statistics import (  # type: ignore
        resolve_win_loss, compute_overview, compute_untp_stats, compute_fixed_untp_overview,
    )


# ── Trade dict factory ─────────────────────────────────────────────────────────

def _t(**overrides) -> dict:
    """
    Minimal trade dict. Defaults represent a healthy hit_tp trade.
    Override only the fields each test cares about.
    """
    base = {
        # Identity / inclusion
        "price_path_captured":  True,
        "entry_time":           "2026-02-24",

        # Trade walk outcome
        "outcome_at_user_tp":   "hit_tp",
        "pnl_r":                1.0,

        # Distance (needed for pips unit conversion)
        "sl_distance_pips":     10.0,

        # MFE / MAE (trade walk)
        "mfe_r":                1.0,
        "mae_r":                0.1,

        # Breakeven state (needed for compute_untp_stats)
        "breakeven_triggered":  False,

        # 14 UNTP checkpoints (default: alive=True, mfe=1.0, mae=0.1)
        **{f"mfe_at_{k}_r":   1.0   for k in [
            "30min","1h","2h","4h","8h","12h",
            "24h","48h","72h","120h","168h","240h","336h","504h"]},
        **{f"mae_at_{k}_r":   0.1   for k in [
            "30min","1h","2h","4h","8h","12h",
            "24h","48h","72h","120h","168h","240h","336h","504h"]},
        **{f"alive_at_{k}":   True  for k in [
            "30min","1h","2h","4h","8h","12h",
            "24h","48h","72h","120h","168h","240h","336h","504h"]},
        **{f"outcome_at_{k}": "hit_tp" for k in [
            "30min","1h","2h","4h","8h","12h",
            "24h","48h","72h","120h","168h","240h","336h","504h"]},
    }
    base.update(overrides)
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP A — resolve_win_loss: original_tp mode
# Covers S6.2 partially, plus S6.4 extension
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_4a_original_tp_hit_tp_is_win():
    """hit_tp → win in original_tp mode."""
    assert resolve_win_loss(
        _t(outcome_at_user_tp="hit_tp", pnl_r=2.0),
        tp_mode="original_tp", tp_value=None, time_limit_hours=None
    ) == "win"


def test_S6_4b_original_tp_hit_sl_is_loss():
    """hit_sl → loss in original_tp mode."""
    assert resolve_win_loss(
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
        tp_mode="original_tp", tp_value=None, time_limit_hours=None
    ) == "loss"


def test_S6_2_original_tp_hit_be_is_loss():
    """
    S6.2 partial — hit_be = LOSS in original_tp mode.

    Rule R7: hit_be context split.
      Statistics win-rate (original_tp) → hit_be = loss
      Streak                            → hit_be = skip
    These are different contexts. This test covers the statistics context.
    """
    assert resolve_win_loss(
        _t(outcome_at_user_tp="hit_be", pnl_r=0.0),
        tp_mode="original_tp", tp_value=None, time_limit_hours=None
    ) == "loss", "hit_be must be classified as loss in original_tp mode (R7)"


def test_S6_4c_original_tp_open_is_inconclusive():
    """open → inconclusive in original_tp mode (not a win or loss)."""
    assert resolve_win_loss(
        _t(outcome_at_user_tp="open", pnl_r=None),
        tp_mode="original_tp", tp_value=None, time_limit_hours=None
    ) == "inconclusive"


def test_S6_4d_original_tp_none_is_inconclusive():
    """none (no TP set) → inconclusive in original_tp mode."""
    assert resolve_win_loss(
        _t(outcome_at_user_tp="none", pnl_r=None),
        tp_mode="original_tp", tp_value=None, time_limit_hours=None
    ) == "inconclusive"


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP B — resolve_win_loss: fixed_tp (trade walk peak), no time limit
# Covers S6.5 extension (formerly fixed_rr — DECISION-15)
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_5a_fixed_tp_no_limit_win_when_mfe_reaches_target():
    """
    fixed_tp, no time limit: mfe_r >= target → win.
    Uses trade-walk peak mfe_r, not UNTP snapshot.
    """
    result = resolve_win_loss(
        _t(mfe_r=2.5),
        tp_mode="fixed_tp", tp_value=2.0, time_limit_hours=None
    )
    assert result == "win", f"mfe_r=2.5 >= target=2.0 → should be win, got {result!r}"


def test_S6_5b_fixed_tp_no_limit_loss_when_sl_hit_before_target():
    """
    fixed_tp, no time limit: mfe_r < target AND hit_sl → loss.
    Trade was closed at SL before reaching the fixed R target.
    """
    result = resolve_win_loss(
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0, mfe_r=0.5),
        tp_mode="fixed_tp", tp_value=2.0, time_limit_hours=None
    )
    assert result == "loss", f"hit_sl with mfe_r=0.5 < target=2.0 → loss, got {result!r}"


def test_S6_5c_fixed_tp_no_limit_inconclusive_when_open_below_target():
    """
    fixed_tp, no time limit: mfe_r < target AND open → inconclusive.
    Trade never reached target AND was not stopped out — still running.
    """
    result = resolve_win_loss(
        _t(outcome_at_user_tp="open", pnl_r=None, mfe_r=0.8),
        tp_mode="fixed_tp", tp_value=2.0, time_limit_hours=None
    )
    assert result == "inconclusive"


def test_S6_5d_fixed_tp_no_limit_hit_be_below_target_is_loss():
    """
    fixed_tp, no time limit: mfe_r < target AND hit_be → loss.
    hit_be means SL was effectively hit (at entry). Same as hit_sl for fixed_tp.
    """
    result = resolve_win_loss(
        _t(outcome_at_user_tp="hit_be", pnl_r=0.0, mfe_r=0.3),
        tp_mode="fixed_tp", tp_value=2.0, time_limit_hours=None
    )
    assert result == "loss"


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP C — compute_fixed_untp_overview: UNTP peak MFE vs target
# fixed_untp uses compute_fixed_untp_overview(), not resolve_win_loss().
# Semantic: win = mfe_at_Xh_r >= target (peak is frozen at UNTP stop if stopped
# early — so alive_at_Xh is irrelevant. Did it ever touch the target? Yes/no.)
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_6a_fixed_untp_win_when_mfe_reaches_target():
    """
    fixed_untp 1h: mfe_at_1h_r=2.5 >= 2.0 target → win.
    trade-walk mfe_r deliberately low — must NOT influence result.
    """
    trade = _t(mfe_at_1h_r=2.5, alive_at_1h=True, mfe_r=0.1)
    r = compute_fixed_untp_overview([trade], tp_value=2.0, time_limit_hours=1.0)
    assert r["wins"]   == 1, f"wins={r['wins']}, expected 1"
    assert r["losses"] == 0


def test_S6_6b_fixed_untp_loss_when_mfe_below_target():
    """
    fixed_untp 1h: mfe_at_1h_r=1.2 < 2.0 target → loss, regardless of alive.
    """
    trade = _t(mfe_at_1h_r=1.2, alive_at_1h=True)
    r = compute_fixed_untp_overview([trade], tp_value=2.0, time_limit_hours=1.0)
    assert r["wins"]   == 0
    assert r["losses"] == 1, f"losses={r['losses']}, expected 1"


def test_S6_6c_fixed_untp_stopped_early_but_hit_target_is_win():
    """
    Key semantic: UNTP walk stopped before 1h (alive=False) but mfe_at_1h_r=2.5
    (frozen at UNTP stop value) >= 2.0 → WIN.
    alive_at_Xh is irrelevant — only peak MFE matters.
    """
    trade = _t(mfe_at_1h_r=2.5, alive_at_1h=False, mfe_r=0.1)
    r = compute_fixed_untp_overview([trade], tp_value=2.0, time_limit_hours=1.0)
    assert r["wins"] == 1, (
        f"wins={r['wins']}, expected 1. "
        f"UNTP stopped early but mfe_at_1h_r=2.5 >= target=2.0 → win."
    )


def test_S6_6d_fixed_untp_none_mfe_is_inconclusive():
    """
    mfe_at_Xh_r=None (no UNTP data) → inconclusive. Not a win or loss.
    Confirms checkpoint column mapping for 4h window.
    """
    trade = _t(mfe_at_4h_r=None, alive_at_4h=False)
    r = compute_fixed_untp_overview([trade], tp_value=2.0, time_limit_hours=4.0)
    assert r["inconclusive_count"] == 1, f"inconclusive_count={r['inconclusive_count']}, expected 1"
    assert r["wins"]   == 0
    assert r["losses"] == 0


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP D — resolve_win_loss: fixed_tp with unit='pips'
# Covers S6.7 extension (formerly fixed_pips mode — DECISION-15)
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_7a_fixed_tp_pips_converts_to_r_and_wins():
    """
    fixed_tp + unit='pips', no time limit: tp_value=20 pips, sl_distance_pips=10.
    rr_target = 20/10 = 2.0R. mfe_r=2.5 >= 2.0 → win.
    """
    trade = _t(sl_distance_pips=10.0, mfe_r=2.5)
    result = resolve_win_loss(
        trade, tp_mode="fixed_tp", tp_value=20.0, time_limit_hours=None, unit="pips"
    )
    assert result == "win", (
        f"fixed_tp pips: 20pip/10pip SL = 2.0R target; mfe_r=2.5 → win; got {result!r}"
    )


def test_S6_7b_fixed_tp_pips_sl_zero_is_inconclusive():
    """
    fixed_tp + unit='pips': sl_distance_pips=0 → inconclusive (division guard).
    Prevents division by zero in pip→R conversion.
    """
    trade = _t(sl_distance_pips=0, mfe_r=5.0)
    result = resolve_win_loss(
        trade, tp_mode="fixed_tp", tp_value=20.0, time_limit_hours=None, unit="pips"
    )
    assert result == "inconclusive", "sl_distance_pips=0 must return inconclusive (division guard)"


def test_S6_7c_fixed_tp_pips_tp_value_none_is_inconclusive():
    """fixed_tp + unit='pips' with tp_value=None → inconclusive (no target defined)."""
    trade = _t(sl_distance_pips=10.0, mfe_r=5.0)
    result = resolve_win_loss(
        trade, tp_mode="fixed_tp", tp_value=None, time_limit_hours=None, unit="pips"
    )
    assert result == "inconclusive"


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP E — compute_fixed_untp_overview: S6.1 (core fixed_untp scenario)
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_1_fixed_untp_win_loss_based_on_untp_peak_mfe():
    """
    fixed_untp core scenario.

    Dataset: 10 trades, time_limit=1h, target=2.0R
      5 × alive=True,  mfe_at_1h_r=2.5 → win  (reached target while still running)
      2 × alive=True,  mfe_at_1h_r=1.0 → loss (alive but never reached target)
      2 × alive=False, mfe_at_1h_r=2.5 → WIN  (stopped early but DID reach target)
      1 × alive=False, mfe_at_1h_r=0.3 → loss (stopped early, never reached target)

    All 10 trades are evaluated — alive_at_Xh is irrelevant.
    Win  = mfe_at_Xh_r >= 2.0  → 5 + 2 = 7 wins
    Loss = mfe_at_Xh_r <  2.0  → 2 + 1 = 3 losses
    win_rate = 7/10 = 70.0%
    """
    trades = (
        [_t(mfe_at_1h_r=2.5, alive_at_1h=True)]  * 5 +
        [_t(mfe_at_1h_r=1.0, alive_at_1h=True,
            outcome_at_user_tp="hit_sl", pnl_r=-1.0)] * 2 +
        [_t(mfe_at_1h_r=2.5, alive_at_1h=False)] * 2 +
        [_t(mfe_at_1h_r=0.3, alive_at_1h=False,
            outcome_at_user_tp="hit_sl", pnl_r=-1.0)] * 1
    )

    r = compute_fixed_untp_overview(trades, tp_value=2.0, time_limit_hours=1.0)

    assert r["wins"]            == 7,  f"wins={r['wins']}, expected 7"
    assert r["losses"]          == 3,  f"losses={r['losses']}, expected 3"
    assert r["evaluated_count"] == 10, f"evaluated_count={r['evaluated_count']}, expected 10"
    assert r["inconclusive_count"] == 0
    assert r["win_rate"] == pytest.approx(70.0, abs=0.2), (
        f"win_rate={r['win_rate']}, expected 70.0%"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP F — compute_overview: S6.2 (hit_be = loss in original_tp mode)
# The exact scenario from Test_Scenarios.md S6.2
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_2_full_hit_be_counts_as_loss_in_original_tp_win_rate():
    """
    Test_Scenarios.md S6.2 — exact scenario.

    Dataset:
      3 × hit_tp  (pnl_r=+1.0 each)
      2 × hit_sl  (pnl_r=-1.0 each)
      1 × hit_be  (pnl_r= 0.0)      ← counts as LOSS in original_tp
      1 × open    (pnl_r=None)       ← inconclusive
      1 × price_path_captured=False  ← excluded entirely

    Query: original_tp, no time limit

    EXPECTED:
      excluded       = 1
      evaluated      = 6  (3+2+1; open is inconclusive, excluded is excluded)
      wins           = 3
      losses         = 3  (2 hit_sl + 1 hit_be)
      win_rate       = 50.0%
    """
    trades = [
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
        _t(outcome_at_user_tp="hit_be", pnl_r=0.0),
        _t(outcome_at_user_tp="open",   pnl_r=None),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0, price_path_captured=False),  # excluded
    ]

    r = compute_overview(trades, tp_mode="original_tp", tp_value=None, time_limit_hours=None)

    assert r["excluded_count"]  == 1, f"excluded_count={r['excluded_count']}, expected 1"
    assert r["wins"]            == 3, f"wins={r['wins']}, expected 3"
    assert r["losses"]          == 3, (
        f"losses={r['losses']}, expected 3 (2 hit_sl + 1 hit_be). "
        f"hit_be must count as loss in original_tp mode (R7)."
    )
    assert r["evaluated_count"] == 6, f"evaluated_count={r['evaluated_count']}, expected 6"
    assert r["win_rate"]        == pytest.approx(50.0, abs=0.1), (
        f"win_rate={r['win_rate']}, expected 50.0%"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP G — compute_overview: S6.3 (net_rr = sum of pnl_r)
# The exact scenario from Test_Scenarios.md S6.3
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_3_net_rr_is_sum_of_pnl_r_only():
    """
    Test_Scenarios.md S6.3 — exact scenario.

    Dataset (original_tp mode):
      hit_tp  pnl_r=+2.0
      hit_tp  pnl_r=+1.5
      hit_sl  pnl_r=-1.0
      hit_be  pnl_r= 0.0
      open    pnl_r=None  ← inconclusive — does NOT contribute to net_rr
      excluded             ← excluded   — does NOT contribute to net_rr

    EXPECTED: net_rr = 2.0 + 1.5 + (-1.0) + 0.0 = +2.5
    """
    trades = [
        _t(outcome_at_user_tp="hit_tp", pnl_r=2.0),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.5),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
        _t(outcome_at_user_tp="hit_be", pnl_r=0.0),
        _t(outcome_at_user_tp="open",   pnl_r=None),
        _t(outcome_at_user_tp="hit_tp", pnl_r=5.0, price_path_captured=False),  # excluded
    ]

    r = compute_overview(trades, tp_mode="original_tp", tp_value=None, time_limit_hours=None)

    assert r["net_rr"] == pytest.approx(2.5, abs=0.001), (
        f"net_rr={r['net_rr']}, expected +2.5. "
        f"net_rr = sum of pnl_r for evaluated trades only (R2)."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP H — compute_overview: S6.9 (excluded never affect stats)
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_9_excluded_trades_never_in_numerator_or_denominator():
    """
    S6.9: price_path_captured=False trades must be completely invisible
    to wins, losses, win_rate, net_rr, and evaluated_count.
    They are only counted in excluded_count.

    Two otherwise identical datasets (with/without excluded trade)
    must produce identical win_rate, net_rr, evaluated_count.
    """
    base_trades = [
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
    ]
    trades_with_excluded = base_trades + [
        _t(outcome_at_user_tp="hit_tp", pnl_r=10.0, price_path_captured=False),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-10.0, price_path_captured=False),
    ]

    r_base = compute_overview(base_trades,          "original_tp", None, None)
    r_excl = compute_overview(trades_with_excluded, "original_tp", None, None)

    assert r_excl["win_rate"]        == r_base["win_rate"],        "win_rate changed by excluded trades"
    assert r_excl["net_rr"]          == r_base["net_rr"],          "net_rr changed by excluded trades"
    assert r_excl["evaluated_count"] == r_base["evaluated_count"], "evaluated_count changed by excluded"
    assert r_excl["excluded_count"]  == 2,                         "excluded_count should be 2"


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP I — compute_overview: equity curve and drawdown (S6.10, S6.11)
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_10_equity_curve_is_cumulative():
    """
    S6.10: equity curve = running cumulative pnl_r.
    3 trades: +2.0, -1.0, +1.5.
    Curve: [2.0, 1.0, 2.5].
    """
    trades = [
        _t(outcome_at_user_tp="hit_tp", pnl_r=2.0, entry_time="2026-02-24"),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0, entry_time="2026-02-25"),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.5, entry_time="2026-02-26"),
    ]

    r = compute_overview(trades, "original_tp", None, None)
    curve_values = [point[1] for point in r["equity_curve"]]

    assert len(curve_values) == 3, f"equity_curve has {len(curve_values)} points, expected 3"
    assert curve_values[0] == pytest.approx(2.0,  abs=0.001)
    assert curve_values[1] == pytest.approx(1.0,  abs=0.001)
    assert curve_values[2] == pytest.approx(2.5,  abs=0.001)


def test_S6_11_max_drawdown_calculated_correctly():
    """
    S6.11: max_drawdown = largest peak-to-trough on equity curve.
    Trades: +3.0, -1.0, -1.0 → equity: 3.0, 2.0, 1.0.
    Peak=3.0, trough=1.0, drawdown=2.0.
    """
    trades = [
        _t(outcome_at_user_tp="hit_tp", pnl_r=3.0),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
    ]

    r = compute_overview(trades, "original_tp", None, None)

    assert r["max_drawdown"] == pytest.approx(2.0, abs=0.001), (
        f"max_drawdown={r['max_drawdown']}, expected 2.0 (peak 3.0 → trough 1.0)"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP J — compute_overview: streaks (S6.12)
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_12a_win_streak_counted_correctly():
    """
    S6.12a: max_win_streak = longest consecutive win run.
    W W W L W W → max_win_streak=3.
    """
    trades = [
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
    ]

    r = compute_overview(trades, "original_tp", None, None)

    assert r["max_win_streak"]  == 3, f"max_win_streak={r['max_win_streak']}, expected 3"
    assert r["max_loss_streak"] == 1, f"max_loss_streak={r['max_loss_streak']}, expected 1"


def test_S6_12b_inconclusive_does_not_break_streak():
    """
    S6.12b: inconclusive (open/none) trades are skipped in streak counting.
    W W OPEN W W → still a streak of 4 wins (OPEN is skipped).

    This mirrors R5 behaviour in mfe_calculator._compute_streak() but for
    compute_overview's internal streak tracking.
    """
    trades = [
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="open",   pnl_r=None),   # inconclusive — skip
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
    ]

    r = compute_overview(trades, "original_tp", None, None)

    assert r["max_win_streak"] == 4, (
        f"max_win_streak={r['max_win_streak']}, expected 4. "
        f"Inconclusive (open) should not break the win streak."
    )


def test_S6_12c_loss_streak_counted_correctly():
    """S6.12c: max_loss_streak = longest consecutive loss run."""
    trades = [
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
    ]

    r = compute_overview(trades, "original_tp", None, None)

    assert r["max_loss_streak"] == 3, f"max_loss_streak={r['max_loss_streak']}, expected 3"
    assert r["max_win_streak"]  == 1, f"max_win_streak={r['max_win_streak']}, expected 1"


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP K — compute_overview: misc fields (S6.13, S6.14, S6.15)
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_13_open_none_are_inconclusive_in_original_tp():
    """
    S6.13: open/none → inconclusive in original_tp. They are NOT losses.
    Denominator = wins + losses only. Inconclusive does not divide.

    Dataset: 1 win, 1 loss, 1 open, 1 none.
    evaluated_count = 2, win_rate = 50%, inconclusive = 2.
    """
    trades = [
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
        _t(outcome_at_user_tp="open",   pnl_r=None),
        _t(outcome_at_user_tp="none",   pnl_r=None),
    ]

    r = compute_overview(trades, "original_tp", None, None)

    assert r["evaluated_count"]    == 2,    f"evaluated_count={r['evaluated_count']}, expected 2"
    assert r["inconclusive_count"] == 2,    f"inconclusive_count={r['inconclusive_count']}, expected 2"
    assert r["win_rate"]           == pytest.approx(50.0, abs=0.1)


def test_S6_14_avg_win_loss_r_computed_correctly():
    """
    S6.14: avg_win_r = average pnl_r of wins; avg_loss_r = average pnl_r of losses.
    Wins: +2.0, +1.0 → avg = 1.5
    Losses: -1.0 → avg = -1.0
    """
    trades = [
        _t(outcome_at_user_tp="hit_tp", pnl_r=2.0),
        _t(outcome_at_user_tp="hit_tp", pnl_r=1.0),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
    ]

    r = compute_overview(trades, "original_tp", None, None)

    assert r["avg_win_r"]  == pytest.approx(1.5,  abs=0.001), f"avg_win_r={r['avg_win_r']}"
    assert r["avg_loss_r"] == pytest.approx(-1.0, abs=0.001), f"avg_loss_r={r['avg_loss_r']}"


def test_S6_15_outcome_breakdown_counts_all_outcomes():
    """
    S6.15: outcome_breakdown counts raw outcome_at_user_tp for each bucket.
    Excluded trades (price_path_captured=False) are NOT in the breakdown.
    """
    trades = [
        _t(outcome_at_user_tp="hit_tp"),
        _t(outcome_at_user_tp="hit_tp"),
        _t(outcome_at_user_tp="hit_sl"),
        _t(outcome_at_user_tp="hit_be"),
        _t(outcome_at_user_tp="open"),
        _t(outcome_at_user_tp="none"),
        _t(outcome_at_user_tp="hit_tp", price_path_captured=False),  # excluded
    ]

    r = compute_overview(trades, "original_tp", None, None)
    bd = r["outcome_breakdown"]

    assert bd["hit_tp"] == 2, f"hit_tp={bd['hit_tp']}, expected 2 (excluded not counted)"
    assert bd["hit_sl"] == 1
    assert bd["hit_be"] == 1
    assert bd["open"]   == 1
    assert bd["none"]   == 1


def test_S6_16_expectancy_is_net_rr_divided_by_evaluated():
    """
    expectancy = net_rr / evaluated_count.
    1 win (+2.0), 1 loss (-1.0) → net_rr=1.0, evaluated=2, expectancy=0.5.
    """
    trades = [
        _t(outcome_at_user_tp="hit_tp", pnl_r=2.0),
        _t(outcome_at_user_tp="hit_sl", pnl_r=-1.0),
    ]

    r = compute_overview(trades, "original_tp", None, None)

    assert r["net_rr"]     == pytest.approx(1.0, abs=0.001)
    assert r["expectancy"] == pytest.approx(0.5, abs=0.001), (
        f"expectancy={r['expectancy']}, expected 0.5 (net_rr/evaluated = 1.0/2)"
    )


def test_S6_17_empty_trade_list_returns_zero_metrics():
    """
    Edge case: empty trade list → no crash, all counts are zero.
    win_rate=0, net_rr=0, evaluated_count=0.
    """
    r = compute_overview([], "original_tp", None, None)

    assert r["total_trades"]    == 0
    assert r["evaluated_count"] == 0
    assert r["wins"]            == 0
    assert r["losses"]          == 0
    assert r["win_rate"]        == 0.0
    assert r["net_rr"]          == 0.0
    assert r["equity_curve"]    == []


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP L — compute_untp_stats: BE-split groups (DECISION-15)
# Covers untp_overview mode. Function: compute_untp_stats().
# Returns: result_type='untp_stats', groups stats_all/stats_be_active/stats_no_be.
# Per-group fields: open_count / sl_count / be_count.
# ═══════════════════════════════════════════════════════════════════════════════

def test_S6_18_untp_overview_splits_by_breakeven_triggered():
    """
    compute_untp_stats splits trades into two groups by breakeven_triggered.
    stats_be_active = trades where breakeven_triggered=True.
    stats_no_be     = trades where breakeven_triggered=False.
    """
    trades = [
        _t(breakeven_triggered=True,  alive_at_1h=True),
        _t(breakeven_triggered=True,  alive_at_1h=True),
        _t(breakeven_triggered=False, alive_at_1h=True),
    ]

    r = compute_untp_stats(trades, time_limit_hours=1.0)

    assert r["result_type"]                  == "untp_stats"
    assert r["stats_be_active"]["total"]     == 2
    assert r["stats_no_be"]["total"]         == 1


def test_S6_19_untp_overview_open_sl_be_counts():
    """
    Per-group counts: Open (alive=True), SL (alive=False+be=False),
    BE (alive=False+be=True).

    Group stats_no_be (no BE config):
      2 × alive=True  → open_count
      1 × alive=False, breakeven_triggered=False → sl_count
    """
    trades = [
        _t(breakeven_triggered=False, alive_at_4h=True,  mfe_at_4h_r=1.5),
        _t(breakeven_triggered=False, alive_at_4h=True,  mfe_at_4h_r=1.0),
        _t(breakeven_triggered=False, alive_at_4h=False),
    ]

    r = compute_untp_stats(trades, time_limit_hours=4.0)
    g = r["stats_no_be"]

    assert g["open_count"] == 2, f"open_count={g['open_count']}, expected 2"
    assert g["sl_count"]   == 1, f"sl_count={g['sl_count']}, expected 1"
    assert g["be_count"]   == 0, f"be_count={g['be_count']}, expected 0"


def test_S6_20_untp_overview_stopped_be_goes_to_be_count():
    """
    alive=False AND breakeven_triggered=True → be_count (not sl_count).
    alive=True  AND breakeven_triggered=True → open_count.
    """
    trades = [
        _t(breakeven_triggered=True, alive_at_2h=False),
        _t(breakeven_triggered=True, alive_at_2h=True, mfe_at_2h_r=0.8),
    ]

    r = compute_untp_stats(trades, time_limit_hours=2.0)
    g = r["stats_be_active"]

    assert g["open_count"] == 1, f"open_count={g['open_count']}, expected 1"
    assert g["be_count"]   == 1, f"be_count={g['be_count']}, expected 1"
    assert g["sl_count"]   == 0, f"sl_count={g['sl_count']}, expected 0"


def test_S6_21_untp_overview_excluded_not_in_groups():
    """
    price_path_captured=False trades excluded from all three pre-computed groups.
    """
    trades = [
        _t(breakeven_triggered=False, alive_at_1h=True),
        _t(breakeven_triggered=False, alive_at_1h=True, price_path_captured=False),  # excluded
    ]

    r = compute_untp_stats(trades, time_limit_hours=1.0)

    assert r["excluded_count"]           == 1
    assert r["stats_no_be"]["total"]     == 1
    assert r["stats_be_active"]["total"] == 0


def test_S6_22_untp_overview_empty_group_no_crash():
    """
    Group with zero trades: total=0, all counts=0, no division error.
    avg_open_mfe_r and avg_open_mae_r are 0.0 when no Open trades exist.
    """
    trades = [
        _t(breakeven_triggered=False, alive_at_1h=True),
    ]

    r = compute_untp_stats(trades, time_limit_hours=1.0)

    g_be = r["stats_be_active"]
    assert g_be["total"]          == 0
    assert g_be["open_count"]     == 0
    assert g_be["sl_count"]       == 0
    assert g_be["be_count"]       == 0
    assert g_be["avg_open_mfe_r"] == 0.0
    assert g_be["avg_open_mae_r"] == 0.0