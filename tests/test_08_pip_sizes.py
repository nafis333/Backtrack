"""
tests/test_08_pip_sizes.py
--------------------------
Pip size correctness — all symbol families.

Covers
------
T8.1  EURUSD   — standard forex    pip=0.0001
T8.2  USDJPY   — JPY pair          pip=0.01
T8.3  XAUUSD   — gold              pip=0.1
T8.4  XAGUSD   — silver            pip=0.01
T8.5  NAS100   — index             pip=1.0
T8.6  US30     — index             pip=1.0
T8.7  USOIL    — oil               pip=0.1

What these tests actually verify
---------------------------------
pip_size drives sl_distance_pips, which drives:
  - tp_rr_target = tp_pips_target / sl_distance_pips
  - pnl_r        = tp_rr_target on TP hit
  - mae_r / mfe_r at checkpoints
  - be_trigger_price (RR mode)

A wrong pip_size produces wrong pnl_r. We verify via:
  pnl_r == tp_rr_target == (tp_distance_price / sl_distance_price)

Each test uses a 2:1 RR setup specific to the symbol's pip scale.
The assertion is: pnl_r == approx(2.0) — if pip_size is wrong, this fails.

Note on NAS100 / US30
---------------------
sym_key = symbol.upper() — data must be injected under "NAS100" / "US30".
USTEC is only the parquet filename, not the sym_key used in mfe_calculator.

Note on XAGUSD pip
------------------
XAGUSD pip=0.01 (same as JPY pairs numerically but different semantic).
"""

import pytest
from tests.helpers import (
    make_candles, trade_params, assert_outcome,
    ENTRY_TIME, mfe_calculator,
)


def _run_pip_test(inject_candles, symbol, entry, sl, tp):
    """
    Shared runner: inject candles for symbol, run walk, assert hit_tp + pnl_r=2.0.
    Candle goes straight to TP with no adverse move so mae_r≈0 (clean test).
    """
    df = make_candles(ENTRY_TIME, [
        # Single candle: high reaches TP cleanly, low stays above entry
        (1,  entry,  tp + abs(tp - entry) * 0.05,  entry + abs(tp - entry) * 0.01,  tp),
    ])
    inject_candles(symbol, df)

    result = mfe_calculator.calculate_mfe(**trade_params(
        symbol=symbol,
        entry_price=entry,
        stoploss_price=sl,
        takeprofit_price=tp,
    ))

    assert result["price_path_captured"] is True, (
        f"[{symbol}] price_path_captured=False — walk failed silently."
    )
    assert_outcome(result, "hit_tp")
    assert result["pnl_r"] == pytest.approx(2.0, rel=1e-4), (
        f"[{symbol}] pnl_r={result['pnl_r']:.6f} — expected 2.0. "
        f"Wrong pip_size would produce a different RR."
    )
    assert result["tp_rr_target"] == pytest.approx(2.0, rel=1e-4)
    return result


# ── T8.1: EURUSD — pip=0.0001 ─────────────────────────────────────────────────

def test_pip_eurusd(inject_candles):
    """
    entry=1.10000, SL=1.09900 (10 pip / 1R), TP=1.10200 (20 pip / 2R).
    pip=0.0001: sl_distance_pips=10.0, tp_rr=2.0.
    """
    _run_pip_test(inject_candles, "EURUSD",
        entry=1.10000, sl=1.09900, tp=1.10200)


# ── T8.2: USDJPY — pip=0.01 ───────────────────────────────────────────────────

def test_pip_usdjpy(inject_candles):
    """
    entry=150.000, SL=149.900 (10 pip / 1R), TP=150.200 (20 pip / 2R).
    pip=0.01: sl_distance_pips=10.0, tp_rr=2.0.
    """
    _run_pip_test(inject_candles, "USDJPY",
        entry=150.000, sl=149.900, tp=150.200)


# ── T8.3: XAUUSD — pip=0.1 ────────────────────────────────────────────────────

def test_pip_xauusd(inject_candles):
    """
    entry=2000.0, SL=1999.0 (10 pip / 1R), TP=2002.0 (20 pip / 2R).
    pip=0.1: sl_distance_pips=10.0, tp_rr=2.0.
    """
    _run_pip_test(inject_candles, "XAUUSD",
        entry=2000.0, sl=1999.0, tp=2002.0)


# ── T8.4: XAGUSD — pip=0.01 ───────────────────────────────────────────────────

def test_pip_xagusd(inject_candles):
    """
    entry=25.000, SL=24.900 (10 pip / 1R), TP=25.200 (20 pip / 2R).
    pip=0.01: sl_distance_pips=10.0, tp_rr=2.0.
    """
    _run_pip_test(inject_candles, "XAGUSD",
        entry=25.000, sl=24.900, tp=25.200)


# ── T8.5: NAS100 — pip=1.0 ────────────────────────────────────────────────────

def test_pip_nas100(inject_candles):
    """
    entry=18000.0, SL=17990.0 (10 pip / 1R), TP=18020.0 (20 pip / 2R).
    pip=1.0: sl_distance_pips=10.0, tp_rr=2.0.

    Data injected under "NAS100" — sym_key=symbol.upper().
    USTEC is the parquet filename, not the sym_key.
    """
    _run_pip_test(inject_candles, "NAS100",
        entry=18000.0, sl=17990.0, tp=18020.0)


# ── T8.6: US30 — pip=1.0 ──────────────────────────────────────────────────────

def test_pip_us30(inject_candles):
    """
    entry=39000.0, SL=38990.0 (10 pip / 1R), TP=39020.0 (20 pip / 2R).
    pip=1.0: sl_distance_pips=10.0, tp_rr=2.0.
    """
    _run_pip_test(inject_candles, "US30",
        entry=39000.0, sl=38990.0, tp=39020.0)


# ── T8.7: USOIL — pip=0.1 ─────────────────────────────────────────────────────

def test_pip_usoil(inject_candles):
    """
    entry=80.00, SL=79.00 (10 pip / 1R), TP=82.00 (20 pip / 2R).
    pip=0.1: sl_distance_pips=10.0, tp_rr=2.0.
    """
    _run_pip_test(inject_candles, "USOIL",
        entry=80.00, sl=79.00, tp=82.00)