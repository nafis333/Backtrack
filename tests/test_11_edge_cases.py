"""
tests/test_11_edge_cases.py
----------------------------
Graceful failure and boundary edge cases.

Covers
------
T11.1  EC5: unknown symbol → price_path_captured=False, no crash
T11.2  EC6: SL == entry (zero distance) → price_path_captured=False, no crash
T11.3  EC7: single-candle trade → price_path_captured=True, mfe_path has ≥1 entry
T11.4  EC8: trade resolves before 30min → all 14 checkpoints frozen (alive=False)
T11.5  EC9 with TP: data ends before TP hit → outcome='open', pnl_r=None
T11.6  EC9 no TP:   data ends with no TP configured → outcome='none', pnl_r=None

Key rules guarded
-----------------
EC5: sym_key not in data_frames → raises ValueError → outer except catches it →
     returns _empty_result() with price_path_captured=False. Never crashes.

EC6: sl_distance_pips == 0 → raises ValueError before any division.
     Prevents ZeroDivisionError deep in the walk. Returns price_path_captured=False.

EC7: single-candle trade (one candle, TP or SL hit on it).
     mfe_path must have ≥1 entry — the post-walk EC7 guard ensures this.
     price_path_captured=True (trade DID resolve).

EC8: trade resolves before the 30min checkpoint. The first checkpoint candle
     fires snapshot for ALL 14 checkpoints simultaneously, all with alive=False.
     alive_at_Xh=False for every checkpoint regardless of UNTP cap.

EC9: data runs out before trade resolves.
     exit_price = last_close (fallback). pnl_r=None.
     has_tp=True → outcome_stored='open'
     has_tp=False → outcome_stored='none'
"""

import json
import pytest
from tests.helpers import (
    make_candles, trade_params, ENTRY_TIME, mfe_calculator,
)

CHECKPOINT_KEYS = [
    "alive_at_30min", "alive_at_1h",  "alive_at_2h",  "alive_at_4h",
    "alive_at_8h",   "alive_at_12h", "alive_at_24h", "alive_at_48h",
    "alive_at_72h",  "alive_at_120h","alive_at_168h","alive_at_240h",
    "alive_at_336h", "alive_at_504h",
]


# ── T11.1: EC5 — unknown symbol → price_path_captured=False ───────────────────

def test_unknown_symbol_returns_safe_result():
    """
    EC5: Symbol not present in data_frames at all.
    mfe_calculator raises ValueError internally, outer except catches it,
    returns _empty_result() with price_path_captured=False.
    Must not crash. All numeric fields must be None.
    """
    # Do NOT inject candles — "UNKNOWN" not in data_frames
    result = mfe_calculator.calculate_mfe(**trade_params(symbol="UNKNOWN"))

    assert result["price_path_captured"] is False
    assert result["outcome_at_user_tp"]  is None
    assert result["pnl_r"]               is None
    assert result["mfe_r"]               is None


# ── T11.2: EC6 — SL == entry (zero SL distance) → price_path_captured=False ──

def test_zero_sl_distance_returns_safe_result(inject_candles):
    """
    EC6: stoploss_price == entry_price → sl_distance_pips=0 → ValueError.
    Prevents ZeroDivisionError deep in the walk. Returns price_path_captured=False.
    """
    df = make_candles(ENTRY_TIME, [
        (1,  1.10010,  1.10200,  1.10000,  1.10100),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(
        stoploss_price=1.10000,  # == entry_price → zero distance
    ))

    assert result["price_path_captured"] is False
    assert result["pnl_r"]               is None
    assert result["outcome_at_user_tp"]  is None


# ── T11.3: EC7 — single-candle trade → mfe_path has ≥1 entry ─────────────────

def test_single_candle_trade_mfe_path_populated(inject_candles):
    """
    EC7: Trade resolves on the very first candle (TP hit immediately).
    Post-walk EC7 guard ensures mfe_path is never empty.
    Asserts: price_path_captured=True, len(mfe_path) >= 1.
    """
    df = make_candles(ENTRY_TIME, [
        (1,  1.10010,  1.10210,  1.10005,  1.10200),  # TP hit candle 1
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert result["price_path_captured"] is True
    assert result["outcome_at_user_tp"]  == "hit_tp"

    path = json.loads(result["mfe_path_json"])
    assert len(path) >= 1, (
        f"EC7: mfe_path is empty for single-candle trade — post-walk guard failed."
    )
    # Each entry must have 4 fields: [elapsed_min, mfe_r, mae_r, untp_alive]
    assert all(len(entry) == 4 for entry in path), (
        f"mfe_path entries must have 4 fields. Got: {path}"
    )


# ── T11.4: EC8 — resolves before 30min → all 14 checkpoints alive=False ───────

def test_early_resolution_freezes_all_checkpoints(inject_candles):
    """
    EC8: Trade resolves at 5min (before 30min checkpoint).
    When the first candle at elapsed >= 30min fires, it snapshots ALL 14
    checkpoints simultaneously with alive=False (UNTP stopped at SL hit).

    Asserts: every alive_at_Xh field is False.
    """
    df = make_candles(ENTRY_TIME, [
        # SL hit at 5min — resolves well before any checkpoint
        (5,   1.09980,  1.10010,  1.09880,  1.09900),  # lo <= SL 1.09900
        # Candle past 30min to trigger snapshot recording
        (35,  1.09900,  1.09950,  1.09870,  1.09920),
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())

    assert result["outcome_at_user_tp"] == "hit_sl"
    assert result["price_path_captured"] is True

    for key in CHECKPOINT_KEYS:
        assert result[key] is False, (
            f"EC8: {key}={result[key]!r} — expected False. "
            f"All checkpoints must be frozen after early resolution."
        )


# ── T11.5: EC9 with TP — data ends before resolution → outcome='open' ─────────

def test_data_ends_with_tp_outcome_is_open(inject_candles):
    """
    EC9: TP configured. Data runs out before TP or SL is hit.
    outcome_at_user_tp='open', pnl_r=None.
    exit_price falls back to last_close.
    price_path_captured=True (walk ran, just didn't resolve).
    """
    df = make_candles(ENTRY_TIME, [
        # Price drifts up but never reaches TP 1.10200 or SL 1.09900
        (15,  1.10010,  1.10050,  1.10005,  1.10030),
        (30,  1.10030,  1.10080,  1.10020,  1.10060),
        # Data ends here — TP (1.10200) and SL (1.09900) never hit
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params())  # TP=1.10200

    assert result["price_path_captured"] is True
    assert result["outcome_at_user_tp"]  == "open"
    assert result["pnl_r"]               is None
    assert result["exit_price"]          == pytest.approx(1.10060, rel=1e-6)  # last_close


# ── T11.6: EC9 no TP — data ends → outcome='none' ─────────────────────────────

def test_data_ends_without_tp_outcome_is_none(inject_candles):
    """
    EC9: No TP configured. Data runs out before SL is hit.
    outcome_at_user_tp='none' (no TP = 'none', with TP = 'open').
    pnl_r=None.
    """
    df = make_candles(ENTRY_TIME, [
        (15,  1.10010,  1.10050,  1.10005,  1.10030),
        (30,  1.10030,  1.10080,  1.10020,  1.10060),
        # SL (1.09900) never hit — data ends
    ])
    inject_candles("EURUSD", df)

    result = mfe_calculator.calculate_mfe(**trade_params(takeprofit_price=None))

    assert result["price_path_captured"] is True
    assert result["outcome_at_user_tp"]  == "none"
    assert result["pnl_r"]               is None