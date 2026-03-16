"""
tests/test_01_basic_buy.py
--------------------------
Basic buy trade outcomes — no BE, no pending orders.

Covers
------
S1.1  Clean TP hit
S1.2  Clean SL hit
      No-TP trade (outcome='none')
      TP set but data ends before resolution (outcome='open')
      pnl_r is derived from tp_rr_target, NOT from mfe fields (R2)

All tests use EURUSD defaults from trade_params():
  entry=1.10000, SL=1.09900 (10 pip / 1R), TP=1.10200 (20 pip / 2R)
"""

import pytest
from tests.helpers import (
    make_candles, trade_params, assert_outcome, assert_checkpoint,
    ENTRY_TIME, mfe_calculator,
)


# ── T1.1: Clean TP hit (S1.1) ─────────────────────────────────────────────────

def test_buy_hits_tp(inject_candles):
    """
    Price rises cleanly to TP. Low stays above entry — zero adverse move.
    Asserts: outcome, pnl_r, exit_price, no BE, no dip, mae_r≈0.
    """
    df = make_candles(ENTRY_TIME, [
        # offset  open      high      low       close
        # Low 1.10010 > entry 1.10000 — no adverse move at all
        (1,       1.10050,  1.10250,  1.10010,  1.10200),  # high >= TP 1.10200
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert_outcome(result, "hit_tp")
    assert result["pnl_r"]               == pytest.approx(2.0,     rel=1e-6)
    assert result["tp_rr_target"]         == pytest.approx(2.0,     rel=1e-6)
    assert result["exit_price"]           == pytest.approx(1.10200, rel=1e-6)
    assert result["breakeven_triggered"]  is False
    assert result["dip_occurred"]         is False
    assert result["tp_was_reached"]       is True
    assert result["mae_r"]                == pytest.approx(0.0, abs=0.01)  # low > entry → no MAE


# ── T1.2: Clean SL hit (S1.2) ─────────────────────────────────────────────────

def test_buy_hits_sl(inject_candles):
    """
    Price drops immediately to SL. No favourable move at all.
    Asserts: pnl_r=-1.0, exit_price=SL, alive_at_30min=False (UNTP stops at SL).
    """
    df = make_candles(ENTRY_TIME, [
        # offset  open      high      low       close
        (1,       1.09950,  1.09980,  1.09880,  1.09900),  # low <= SL 1.09900
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert_outcome(result, "hit_sl")
    assert result["pnl_r"]               == pytest.approx(-1.0,    rel=1e-6)
    assert result["exit_price"]          == pytest.approx(1.09900,  rel=1e-6)
    assert result["tp_was_reached"]      is False
    assert result["breakeven_triggered"] is False
    # UNTP stops on the same candle as SL hit (SL = UNTP stop condition)
    assert result["alive_at_30min"] is False
    assert_checkpoint(result, "30min", alive=False, outcome="hit_sl")


# ── T1.3: No TP set — outcome='none' ──────────────────────────────────────────

def test_buy_no_tp_outcome_none(inject_candles):
    """
    TP=None. Price runs without hitting SL. Outcome='none', pnl_r=None.
    R2: pnl_r is NULL for open/none — never computed from mfe.
    """
    df = make_candles(ENTRY_TIME, [
        (1,  1.10050, 1.10100, 1.09950, 1.10080),
        (2,  1.10080, 1.10150, 1.09960, 1.10120),
        (3,  1.10120, 1.10200, 1.09970, 1.10180),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(takeprofit_price=None))

    assert result["price_path_captured"] is True
    assert result["outcome_at_user_tp"]  == "none"
    assert result["pnl_r"]               is None
    assert result["rr_at_user_tp"]       is None
    assert result["tp_was_reached"]      is False


# ── T1.4: TP set but data ends — outcome='open' ────────────────────────────────

def test_buy_tp_set_data_ends_outcome_open(inject_candles):
    """
    TP set but candles end before TP or SL hit.
    Outcome='open' (has_tp=True, unresolved), pnl_r=None.
    price_path_captured=True — data was processed, just inconclusive.
    """
    df = make_candles(ENTRY_TIME, [
        # Price drifts up but never reaches TP 1.10200 or SL 1.09900
        (1,  1.10020, 1.10060, 1.09950, 1.10040),
        (2,  1.10040, 1.10080, 1.09960, 1.10060),
        (3,  1.10060, 1.10100, 1.09970, 1.10080),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert result["price_path_captured"] is True
    assert result["outcome_at_user_tp"]  == "open"
    assert result["pnl_r"]               is None
    assert result["rr_at_user_tp"]       is None
    assert result["tp_was_reached"]      is False


# ── T1.5: pnl_r equals tp_rr_target exactly, never derived from mfe ───────────

def test_pnl_r_equals_tp_rr_target_not_mfe(inject_candles):
    """
    TP at 3R. Price runs to 4R (past TP). pnl_r must be exactly 3.0, not 4.0.
    Guards R2: pnl_r is NEVER computed from mfe fields.
    """
    df = make_candles(ENTRY_TIME, [
        # SL=1.09900 (10 pip), TP=1.10300 (30 pip = 3R)
        # High reaches 1.10400 (4R) — past TP, pnl_r must still be 3.0
        (1,  1.10050, 1.10400, 1.10010, 1.10300),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(
        takeprofit_price=1.10300,
    ))

    assert_outcome(result, "hit_tp")
    assert result["tp_rr_target"] == pytest.approx(3.0, rel=1e-6)
    assert result["pnl_r"]        == pytest.approx(3.0, rel=1e-6)
    # mfe_r >= 3.0 because price ran to 4R — but pnl_r must be tp_rr_target not mfe_r
    assert result["mfe_r"]        >= 3.0
    assert result["pnl_r"]        == pytest.approx(result["tp_rr_target"], rel=1e-6)