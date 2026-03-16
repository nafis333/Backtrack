"""
tests/test_12_integration.py
-----------------------------
Integration test — real parquet data, known trade with verified outputs.

What this tests that the unit suite cannot
------------------------------------------
- Real M1 tick structure (not synthetic candles)
- Parquet file loading and column parsing
- Float precision with actual market prices
- End-to-end: real data → calculator → correct field values

Skip behaviour
--------------
If the NZDUSD parquet file is not present (CI, container), all tests
in this file are skipped automatically. The unit suite is unaffected.

Known trade — NZDUSD sell, Feb 26 2026
---------------------------------------
  entry_time:       2026-02-26 19:43:00
  entry_price:      0.59879
  stoploss_price:   0.60137   (25.8 pip above entry = 1R for a sell)
  takeprofit_price: 0.59621   (25.8 pip below entry = 1.0R target)
  trade_type:       sell
  breakeven_active: False

Expected outputs (verified from UI):
  outcome_at_user_tp         = 'hit_tp'
  pnl_r                      = 1.0
  exit_price                 = 0.59621
  tp_rr_target               ≈ 1.0     (±0.01)
  sl_distance_pips           ≈ 25.8    (±0.5)
  mfe_r                      ≈ 1.109   (±0.1)   — frozen at TP candle low
  mae_r                      ≈ 0.078   (±0.03)
  time_to_resolution_minutes ≈ 105     (±5)     — UI shows 1h 45m

Tolerance rationale
-------------------
mfe_r ±0.1: frozen at TP candle low. One pip on a 25.8-pip SL shifts mfe
            by ~0.04R — real M1 lows have more variation than synthetic data.
mae_r ±0.03: very early single candle, tight but allows 1-pip real variation.
time  ±5: M1 candle boundaries; ±5 min allows for rounding differences.
"""

import os
import sys
import pytest
import pandas as pd
from datetime import datetime
from pathlib import Path

# ── Locate parquet file — skip entire module if absent ────────────────────────

_PROJECT_ROOT  = Path(__file__).parent.parent
_STORED_DIR    = _PROJECT_ROOT / "Stored files"
_NZDUSD_FILE   = _STORED_DIR / "NZDUSD.parquet"

if not _NZDUSD_FILE.exists():
    pytest.skip(
        f"Integration tests skipped — parquet file not found: {_NZDUSD_FILE}. "
        f"Run these tests on the machine with 'Stored files/' present.",
        allow_module_level=True,
    )

# ── Import mfe_calculator (same pattern as conftest / helpers) ─────────────────
try:
    import utils.mfe_calculator as mfe_calculator
except ModuleNotFoundError:
    import mfe_calculator  # type: ignore[no-redef]


# ── Load real NZDUSD parquet once for the module ──────────────────────────────

def _load_nzdusd() -> pd.DataFrame:
    """
    Load and parse NZDUSD parquet exactly as data_loader.py does:
      - Parse 'Local time' with format '%d.%m.%Y %H:%M:%S'
      - Drop rows with NaT or null OHLC
    """
    df = pd.read_parquet(_NZDUSD_FILE)
    df["Local time"] = pd.to_datetime(
        df["Local time"],
        format="%d.%m.%Y %H:%M:%S",
        errors="coerce",
    )
    df = df.dropna(subset=["Local time", "Open", "High", "Low", "Close"])
    return df.reset_index(drop=True)


_NZDUSD_DF = _load_nzdusd()


# ── Known trade parameters ────────────────────────────────────────────────────

_KNOWN_TRADE = dict(
    entry_time        = datetime(2026, 2, 26, 19, 43, 0),
    entry_price       = 0.59879,
    stoploss_price    = 0.60137,
    takeprofit_price  = 0.59621,
    trade_type        = "sell",
    symbol            = "NZDUSD",
    limit_price       = None,
    breakeven_active  = False,
    breakeven_type    = None,
    breakeven_value   = None,
    input_type        = "rr",
    channel_id        = 1,
)


# ── T12.1: Core outcome fields ─────────────────────────────────────────────────

def test_nzdusd_outcome_and_pnl(clean_data_frames):
    """
    Primary integration guard.
    Confirms the calculator resolves the known trade correctly
    against real M1 NZDUSD data.

    Asserts: outcome='hit_tp', pnl_r=1.0, exit_price=TP exactly.
    """
    mfe_calculator.data_frames["NZDUSD"] = _NZDUSD_DF

    result = mfe_calculator.calculate_mfe(**_KNOWN_TRADE)

    assert result["price_path_captured"] is True, (
        "price_path_captured=False — data may not cover Feb 26 2026."
    )
    assert result["outcome_at_user_tp"] == "hit_tp", (
        f"Expected hit_tp, got {result['outcome_at_user_tp']!r}. "
        f"Check entry_time and parquet date coverage."
    )
    assert result["pnl_r"]        == pytest.approx(1.0,     rel=1e-6)
    assert result["exit_price"]   == pytest.approx(0.59621, rel=1e-6)
    assert result["tp_rr_target"] == pytest.approx(1.0,     rel=1e-4)


# ── T12.2: SL distance computed correctly from real prices ────────────────────

def test_nzdusd_sl_distance(clean_data_frames):
    """
    sl_distance_pips = |entry - SL| / pip_size
    NZDUSD pip = 0.0001
    |0.59879 - 0.60137| / 0.0001 = 25.8 pips

    Verifies pip_size lookup is correct for NZDUSD (0.0001, not JPY 0.01).
    """
    mfe_calculator.data_frames["NZDUSD"] = _NZDUSD_DF

    result = mfe_calculator.calculate_mfe(**_KNOWN_TRADE)

    assert result["sl_distance_pips"] == pytest.approx(25.8, abs=0.5)


# ── T12.3: MFE and MAE match UI-verified values ───────────────────────────────

def test_nzdusd_mfe_mae(clean_data_frames):
    """
    MFE:    UI shows 1.109R peak in 1h 45m.
    MAE:    UI shows 0.078R peak in 4m.

    mfe_r = mfe_pips_at_close / sl_distance_pips — frozen at the TP candle.
    For this sell: MFE = how far price fell below entry up to the TP candle.
    Peak of 1.109R means the TP candle low reached ~28.6 pip below entry.

    mfe_r and mfe_at_close_r are identical — same underlying value, two keys.

    Tolerance ±0.1R: one pip on a 25.8-pip SL shifts mfe by ~0.04R.
    Real M1 candle lows have more variation than synthetic candles.
    """
    mfe_calculator.data_frames["NZDUSD"] = _NZDUSD_DF

    result = mfe_calculator.calculate_mfe(**_KNOWN_TRADE)

    assert result["mfe_r"] == pytest.approx(1.109, abs=0.1), (
        f"mfe_r={result['mfe_r']:.4f}, expected ≈1.109 (UI value). "
        f"Frozen at TP close candle — candle low determines peak."
    )
    assert result["mae_r"] == pytest.approx(0.078, abs=0.03), (
        f"mae_r={result['mae_r']:.4f}, expected ≈0.078."
    )
    # mfe_r and mfe_at_close_r are identical — same underlying field
    assert result["mfe_at_close_r"] == pytest.approx(result["mfe_r"], rel=1e-9)


# ── T12.4: Resolution time matches UI (1h 45m = 105 min) ─────────────────────

def test_nzdusd_resolution_time(clean_data_frames):
    """
    UI shows exit at Feb 26, 21:28 — entry was 19:43.
    1h 45m = 105 minutes.

    time_to_resolution_minutes = (resolution_candle_time - entry_time).total_seconds() / 60
    Tolerance ±5 min: M1 candle boundaries allow for small rounding differences.
    """
    mfe_calculator.data_frames["NZDUSD"] = _NZDUSD_DF

    result = mfe_calculator.calculate_mfe(**_KNOWN_TRADE)

    assert result["time_to_resolution_minutes"] == pytest.approx(105.0, abs=5.0), (
        f"time_to_resolution={result['time_to_resolution_minutes']:.1f} min, "
        f"expected ≈105 (1h 45m). "
        f"Check parquet data covers 19:43 → 21:28 on 2026-02-26."
    )


# ── T12.5: UNTP alive state — sell with no BE ─────────────────────────────────

def test_nzdusd_untp_state(clean_data_frames):
    """
    Trade hits TP at ~105 min. BE not triggered.
    UNTP stop condition = original SL (0.60137).

    At 30min checkpoint: trade not yet closed, UNTP running → alive=True.
    breakeven_triggered must be False throughout.
    """
    mfe_calculator.data_frames["NZDUSD"] = _NZDUSD_DF

    result = mfe_calculator.calculate_mfe(**_KNOWN_TRADE)

    assert result["breakeven_triggered"] is False
    assert result["alive_at_30min"] is True, (
        "alive_at_30min=False — unexpected. Trade closes at ~105min, "
        "UNTP should still be running at 30min checkpoint."
    )