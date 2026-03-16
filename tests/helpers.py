"""
tests/helpers.py
----------------
Shared test utilities for the Backtrack mfe_calculator test suite.

Public API
----------
make_candles(base_time, rows) -> pd.DataFrame
trade_params(**overrides) -> dict
assert_outcome(result, outcome)
assert_checkpoint(result, key, *, alive, outcome)
mfe_path_times(result) -> list[float]
ENTRY_TIME

Candle row format: (offset_minutes, open, high, low, close)
offset_minutes must be > 0 (candles must be strictly after entry_time).

Float precision: always use pytest.approx() for pnl_r, mfe_r, sl_distance_pips etc.
"""

import json
import pandas as pd
from datetime import datetime, timedelta

# Import mfe_calculator the same way conftest does
try:
    import utils.mfe_calculator as mfe_calculator
except ModuleNotFoundError:
    import mfe_calculator  # type: ignore[no-redef]

ENTRY_TIME = datetime(2024, 1, 15, 10, 0, 0)


# ── Candle builder ─────────────────────────────────────────────────────────────

def make_candles(base_time: datetime, rows: list) -> pd.DataFrame:
    """
    Build a DataFrame for injection into mfe_calculator.data_frames.

    Parameters
    ----------
    base_time : datetime
        Anchor time. For market orders use ENTRY_TIME.
        For pending orders use the order placement time.
    rows : list of (offset_minutes, open, high, low, close)
        offset_minutes > 0 required — candles must be strictly after entry_time.

    Returns
    -------
    pd.DataFrame with columns: Local time, Open, High, Low, Close
    """
    if not rows:
        return pd.DataFrame(columns=["Local time", "Open", "High", "Low", "Close"])

    records = [
        {
            "Local time": base_time + timedelta(minutes=offset),
            "Open":  float(op),
            "High":  float(hi),
            "Low":   float(lo),
            "Close": float(cl),
        }
        for offset, op, hi, lo, cl in rows
    ]
    df = pd.DataFrame(records)
    return df.sort_values("Local time").reset_index(drop=True)


# ── Trade parameter factory ────────────────────────────────────────────────────

# S1.1 defaults: EURUSD buy, entry 1.10000, SL 1.09900 (10 pip/1R), TP 1.10200 (2R)
_DEFAULTS = {
    "entry_time":       ENTRY_TIME,
    "entry_price":      1.10000,
    "stoploss_price":   1.09900,
    "takeprofit_price": 1.10200,
    "trade_type":       "buy",
    "symbol":           "EURUSD",
    "limit_price":      None,
    "breakeven_active": False,
    "breakeven_type":   None,
    "breakeven_value":  None,
    "input_type":       "prices",
    "channel_id":       1,
}


def trade_params(**overrides) -> dict:
    """
    Return a fully-populated kwargs dict for mfe_calculator.calculate_mfe().
    Start from S1.1 defaults; override only what the test needs.

    Usage
    -----
    result = mfe_calculator.calculate_mfe(**trade_params())
    result = mfe_calculator.calculate_mfe(**trade_params(
        trade_type="sell",
        stoploss_price=1.10100,
        takeprofit_price=1.09800,
    ))
    """
    p = dict(_DEFAULTS)
    p.update(overrides)
    return p


# ── Assertion helpers ──────────────────────────────────────────────────────────

def assert_outcome(result: dict, outcome: str):
    """Assert walk completed and outcome matches expected string."""
    assert result["price_path_captured"] is True, (
        "price_path_captured=False — walk failed silently."
    )
    assert result["outcome_at_user_tp"] == outcome, (
        f"Expected outcome={outcome!r}, got {result['outcome_at_user_tp']!r}"
    )


def assert_checkpoint(result: dict, key: str, *, alive: bool, outcome: str):
    """
    Assert a single UNTP checkpoint.
    key: '30min','1h','2h','4h','8h','12h','24h','48h','72h','120h','168h','240h','336h','504h'
    """
    assert result[f"alive_at_{key}"] is alive, (
        f"alive_at_{key}: expected {alive}, got {result[f'alive_at_{key}']}"
    )
    assert result[f"outcome_at_{key}"] == outcome, (
        f"outcome_at_{key}: expected {outcome!r}, got {result[f'outcome_at_{key}']!r}"
    )


def mfe_path_times(result: dict) -> list:
    """Extract elapsed_min values from mfe_path_json as list of floats."""
    raw = result.get("mfe_path_json")
    if raw is None:
        return []
    return [entry[0] for entry in json.loads(raw)]