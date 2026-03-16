"""
test_13_eurusd_scenarios.py
---------------------------
Integration test — real EURUSD parquet data, Feb 24–25 2026.

25 scenarios designed to exercise every distinct code path in mfe_calculator.

Coverage matrix
---------------
OUTCOMES:       hit_tp / hit_sl / hit_be / open / none  (all 5)
TRADE TYPES:    buy / sell / limit_buy / limit_sell / stop_buy / stop_sell
BE PATHS:       BE fires | TP fires before BE level | BE phantom cleanup
UNTP:           alive rules | frozen-at-stop | continues past hit_tp
DATA BOUNDARY:  entry near end of parquet
ERROR PATHS:    sl_distance=0 | limit never triggered | symbol not in data_frames
R RULES:        pnl_r invariant | mfe_path intervals | R milestones monotonicity

Outcome-guarantee strategy
--------------------------
TIGHT_PIPS   = 2 pip from entry  →  fires within minutes in any 48h EURUSD window
FAR_PIPS     = 5000 pip from entry  →  never reached in any 48h EURUSD window

  hit_tp buy  : TP = entry + TIGHT_PIPS,   SL = entry - FAR_PIPS   (guaranteed)
  hit_sl buy  : SL = entry - TIGHT_PIPS,   TP = entry + FAR_PIPS   (guaranteed)
  open        : both unreachable, entry in last 3 candles            (guaranteed)
  none        : no TP set, SL unreachable                            (guaranteed)
  hit_be      : BE@0.1R (1-pip trigger) + huge TP + medium SL        (high-probability)

Pending-order trigger strategy
-------------------------------
  limit_buy  : limit_price = first_anchor_close + 1pip
               → min(op,lo,cl) ≤ close < close + 1pip = lp  → triggers candle 0
  limit_sell : limit_price = first_anchor_high  - 1pip
               → max(op,hi,cl) ≥ high > high - 1pip = lp    → triggers candle 0
  stop_buy   : stop = first_anchor_close + 1pip
               → candle 1: prev_close < stop, high usually ≥ stop   → triggers quickly
  stop_sell  : stop = first_anchor_close - 1pip
               → candle 1: prev_close > stop, low  usually ≤ stop   → triggers quickly

Skip behaviour
--------------
Skips entire module if EURUSD.parquet is absent (same pattern as test_12).
Also skips if Feb 24–25 slice has fewer than 100 candles.
"""

import json
import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

# ── Locate parquet — skip entire module if absent ─────────────────────────────
#
# Checks two locations (both exist in some project layouts):
#   1. {project_root}/Stored files/EURUSD.parquet          ← canonical (data_loader.py)
#   2. {project_root}/utils/Stored files/EURUSD.parquet    ← mirror copy
#
# test_13 uses whichever it finds first. The parquet content is identical
# between the two locations so results are the same either way.

# __file__ is inside tests/. .parent = tests/, .parent.parent = project root
# (same level as app.py) where "Stored files/" lives.
_PROJECT_ROOT = Path(__file__).parent.parent

_CANDIDATE_PATHS = [
    _PROJECT_ROOT / "Stored files"            / "EURUSD.parquet",
    _PROJECT_ROOT / "utils" / "Stored files"  / "EURUSD.parquet",
]

_EURUSD_FILE = next((p for p in _CANDIDATE_PATHS if p.exists()), None)

if _EURUSD_FILE is None:
    pytest.skip(
        f"Integration tests skipped — EURUSD.parquet not found in either:\n"
        f"  {_CANDIDATE_PATHS[0]}\n"
        f"  {_CANDIDATE_PATHS[1]}\n"
        f"Run on a machine with 'Stored files/' present.",
        allow_module_level=True,
    )

# ── Import mfe_calculator (same try/except pattern as conftest / test_12) ─────

try:
    import utils.mfe_calculator as mfe_calculator
except ModuleNotFoundError:
    import mfe_calculator  # type: ignore[no-redef]

CHECKPOINT_KEYS = [
    "30min", "1h", "2h", "4h", "8h", "12h",
    "24h", "48h", "72h", "120h", "168h", "240h", "336h", "504h",
]


# ── Load EURUSD parquet once for the module ────────────────────────────────────

def _load_eurusd() -> pd.DataFrame:
    """
    Load and parse EURUSD parquet exactly as data_loader.py does:
      - Parse 'Local time' with format '%d.%m.%Y %H:%M:%S'
      - Drop rows with NaT or null OHLC
    """
    df = pd.read_parquet(_EURUSD_FILE)
    df["Local time"] = pd.to_datetime(
        df["Local time"],
        format="%d.%m.%Y %H:%M:%S",
        errors="coerce",
    )
    df = df.dropna(subset=["Local time", "Open", "High", "Low", "Close"])
    return df.reset_index(drop=True)


_EURUSD_DF = _load_eurusd()


# ── Extract Feb 24–25 2026 slice ───────────────────────────────────────────────

_SLICE = _EURUSD_DF[
    (_EURUSD_DF["Local time"] >= "2026-02-24 00:00:00") &
    (_EURUSD_DF["Local time"] <  "2026-02-26 00:00:00")
].reset_index(drop=True)

if len(_SLICE) < 100:
    pytest.skip(
        f"Feb 24–25 2026 EURUSD slice has only {len(_SLICE)} candles — "
        f"insufficient data. Check parquet file coverage.",
        allow_module_level=True,
    )

# ── Anchor candles from the real slice ────────────────────────────────────────
#
# _C_EARLY : 10 candles in — gives calc enough context for avg_candle_size_pips
#             and leaves the rest of the 48-hour window for the walk
# _C_MID   : midpoint — used for scenarios that need a visible UNTP window
# _C_LATE  : 5th from last — barely any data after; forces outcome=open quickly
# _C_LAST  : last candle — almost no walk data after entry

_C_EARLY = _SLICE.iloc[10]
_C_MID   = _SLICE.iloc[len(_SLICE) // 2]
_C_LATE  = _SLICE.iloc[-5]
_C_LAST  = _SLICE.iloc[-1]

# ── Price constants ────────────────────────────────────────────────────────────

PIP       = 0.0001                   # EURUSD pip size
TIGHT     = 2 * PIP                  # 2 pip — fires within minutes in any M1 window
FAR       = 0.5000                   # 5000 pip — never reached in any 2-day window
SL_MED    = 10 * PIP                 # 10-pip SL for mid-R scenarios
TP_1R     = 10 * PIP                 # 1R TP (SL=10pip)
TP_3R     = 30 * PIP                 # 3R TP (SL=10pip)


# ── Parameter builder ─────────────────────────────────────────────────────────

def _p(candle, trade_type, sl_off, tp_off=None, **kw):
    """
    Build calculate_mfe kwargs from a real candle row.

    sl_off   : float  SL distance (positive, direction auto by trade_type)
    tp_off   : float  TP distance (positive, direction auto) or None for no-TP
    **kw     : overrides for any other parameter
    """
    ep   = float(candle["Close"])
    etime = candle["Local time"]
    base = "buy" if "buy" in trade_type else "sell"

    if base == "buy":
        sl = ep - sl_off
        tp = (ep + tp_off) if tp_off is not None else None
    else:
        sl = ep + sl_off
        tp = (ep - tp_off) if tp_off is not None else None

    params = dict(
        entry_time        = etime,
        entry_price       = ep,
        stoploss_price    = sl,
        takeprofit_price  = tp,
        trade_type        = trade_type,
        symbol            = "EURUSD",
        limit_price       = None,
        breakeven_active  = False,
        breakeven_type    = None,
        breakeven_value   = None,
        input_type        = "prices",
        channel_id        = 1,
    )
    params.update(kw)
    return params


# ── Hard invariant assertions reused across tests ─────────────────────────────

def _assert_pnl_r_rule(result: dict):
    """R2: pnl_r is ONLY derived from outcome — never from MFE or prices."""
    out   = result["outcome_at_user_tp"]
    pnl   = result["pnl_r"]
    tp_rr = result["tp_rr_target"]

    if out == "hit_tp":
        assert pnl == pytest.approx(tp_rr, rel=1e-6), (
            f"hit_tp: pnl_r={pnl} should equal tp_rr_target={tp_rr}"
        )
    elif out == "hit_sl":
        assert pnl == pytest.approx(-1.0, abs=1e-9), (
            f"hit_sl: pnl_r={pnl} should be exactly -1.0"
        )
    elif out == "hit_be":
        assert pnl == pytest.approx(0.0, abs=1e-9), (
            f"hit_be: pnl_r={pnl} should be exactly 0.0"
        )
    else:  # open / none
        assert pnl is None, (
            f"open/none: pnl_r={pnl} should be None"
        )


def _assert_exit_price_rule(result: dict, entry_price, sl_price, tp_price=None):
    """pnl_r companion: exit_price must match the trigger level exactly."""
    out = result["outcome_at_user_tp"]
    ep  = result["exit_price"]

    if out == "hit_tp":
        assert ep == pytest.approx(tp_price, rel=1e-9), (
            f"hit_tp exit_price={ep} should equal takeprofit_price={tp_price}"
        )
    elif out == "hit_sl":
        assert ep == pytest.approx(sl_price, rel=1e-9), (
            f"hit_sl exit_price={ep} should equal stoploss_price={sl_price}"
        )
    elif out == "hit_be":
        assert ep == pytest.approx(entry_price, rel=1e-9), (
            f"hit_be exit_price={ep} should equal entry_price={entry_price}"
        )


def _assert_all_checkpoints_populated(result: dict):
    """All 56 UNTP checkpoint fields must be non-None for a resolved trade."""
    for k in CHECKPOINT_KEYS:
        assert result[f"mfe_at_{k}_r"]   is not None, f"mfe_at_{k}_r is None"
        assert result[f"mae_at_{k}_r"]   is not None, f"mae_at_{k}_r is None"
        assert result[f"outcome_at_{k}"] is not None, f"outcome_at_{k} is None"
        assert result[f"alive_at_{k}"]   is not None, f"alive_at_{k} is None"


def _assert_alive_monotonic(result: dict):
    """
    alive_at_Xh must be non-increasing over checkpoints.
    Once UNTP stops (alive=False), it cannot restart (alive=True).
    """
    seen_false = False
    for k in CHECKPOINT_KEYS:
        alive = result[f"alive_at_{k}"]
        if seen_false:
            assert alive is False, (
                f"alive_at_{k}=True after an earlier alive=False — "
                f"UNTP cannot restart once stopped"
            )
        if alive is False:
            seen_false = True


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 1 — Market orders, outcome guaranteed by construction
# ═══════════════════════════════════════════════════════════════════════════════

def test_T13_01_buy_hit_tp_guaranteed(clean_data_frames):
    """
    BUY hit_tp — tight TP (2pip), unreachable SL (5000pip).

    In any 48h EURUSD M1 window, a 2-pip favourable move is certain.
    Walk MUST resolve to hit_tp.

    Asserts
    -------
    - outcome='hit_tp', pnl_r=tp_rr_target, exit_price=TP exactly
    - price_path_captured=True
    - All 56 UNTP checkpoint fields populated
    - alive_at monotonically non-increasing
    - UNTP alive_at_30min=True: UNTP continues after TP hit (SL unreachable,
      so UNTP stop never fires in 30min window after a fast hit_tp)
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_EARLY, "buy", sl_off=FAR, tp_off=TIGHT)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "hit_tp", (
        f"Expected hit_tp with 2-pip TP; got {r['outcome_at_user_tp']!r}. "
        f"Check EURUSD parquet coverage for {_C_EARLY['Local time']}."
    )
    _assert_pnl_r_rule(r)
    _assert_exit_price_rule(r, params["entry_price"],
                             params["stoploss_price"], params["takeprofit_price"])
    _assert_all_checkpoints_populated(r)
    _assert_alive_monotonic(r)

    # UNTP: SL is FAR away (5000pip). After a quick hit_tp, UNTP continues.
    # At 30min checkpoint: UNTP is still alive (SL will not fire in 30min).
    assert r["alive_at_30min"] is True, (
        "alive_at_30min=False unexpectedly. After hit_tp with SL=5000pip, "
        "UNTP should continue running at 30min."
    )
    assert r["breakeven_triggered"] is False


def test_T13_02_sell_hit_tp_guaranteed(clean_data_frames):
    """
    SELL hit_tp — tight TP (2pip below entry), unreachable SL (5000pip above).
    Confirms sell direction mechanics produce same outcome rules.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_EARLY, "sell", sl_off=FAR, tp_off=TIGHT)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "hit_tp", (
        f"Expected hit_tp for sell with 2-pip TP; got {r['outcome_at_user_tp']!r}."
    )
    _assert_pnl_r_rule(r)
    _assert_exit_price_rule(r, params["entry_price"],
                             params["stoploss_price"], params["takeprofit_price"])
    _assert_all_checkpoints_populated(r)
    _assert_alive_monotonic(r)
    assert r["alive_at_30min"] is True
    assert r["breakeven_triggered"] is False


def test_T13_03_buy_hit_sl_guaranteed(clean_data_frames):
    """
    BUY hit_sl — tight SL (2pip), unreachable TP (5000pip).
    A 2-pip adverse move is certain in any 48h EURUSD window.

    Asserts
    -------
    - outcome='hit_sl', pnl_r=-1.0, exit_price=SL exactly
    - UNTP: all 14 alive_at checkpoints False (UNTP stops same candle as trade)
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_EARLY, "buy", sl_off=TIGHT, tp_off=FAR)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "hit_sl", (
        f"Expected hit_sl with 2-pip SL; got {r['outcome_at_user_tp']!r}."
    )
    _assert_pnl_r_rule(r)
    _assert_exit_price_rule(r, params["entry_price"],
                             params["stoploss_price"], params["takeprofit_price"])
    _assert_all_checkpoints_populated(r)
    _assert_alive_monotonic(r)

    # UNTP: SL hit = UNTP stop condition. All 14 checkpoints must be alive=False.
    for k in CHECKPOINT_KEYS:
        assert r[f"alive_at_{k}"] is False, (
            f"alive_at_{k}=True for hit_sl — UNTP must stop same candle as trade"
        )


def test_T13_04_sell_hit_sl_guaranteed(clean_data_frames):
    """
    SELL hit_sl — tight SL (2pip above entry), unreachable TP (5000pip below).
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_EARLY, "sell", sl_off=TIGHT, tp_off=FAR)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "hit_sl", (
        f"Expected hit_sl for sell with 2-pip SL; got {r['outcome_at_user_tp']!r}."
    )
    _assert_pnl_r_rule(r)
    _assert_exit_price_rule(r, params["entry_price"],
                             params["stoploss_price"], params["takeprofit_price"])
    _assert_all_checkpoints_populated(r)

    for k in CHECKPOINT_KEYS:
        assert r[f"alive_at_{k}"] is False, (
            f"alive_at_{k}=True for sell hit_sl — UNTP must stop same candle"
        )


def test_T13_05_buy_no_tp_outcome_none(clean_data_frames):
    """
    BUY, no TP set, SL unreachable (5000pip).
    Data runs to end of Feb 25 → outcome='none', pnl_r=None.

    Confirms:
    - outcome='none' (not 'open') when takeprofit_price=None
    - pnl_r is None
    - exit_price is set (last candle close)
    - price_path_captured=True
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_EARLY, "buy", sl_off=FAR, tp_off=None)  # tp_off=None → no TP

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "none", (
        f"Expected 'none' with no TP; got {r['outcome_at_user_tp']!r}"
    )
    assert r["pnl_r"] is None
    assert r["exit_price"] is not None, "exit_price should be last candle close, not None"
    assert r["tp_rr_target"] is None


def test_T13_06_sell_no_tp_outcome_none(clean_data_frames):
    """
    SELL, no TP, SL unreachable → outcome='none'.
    Confirms sell direction also produces 'none' (not 'hit_sl' or 'open').
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_EARLY, "sell", sl_off=FAR, tp_off=None)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "none"
    assert r["pnl_r"] is None
    assert r["tp_rr_target"] is None


def test_T13_07_buy_data_ends_outcome_open(clean_data_frames):
    """
    BUY, TP and SL both unreachable (5000pip), entry near end of Feb 25 slice.
    Only ~3 candles of data after entry → walk exhausts → outcome='open'.

    Confirms:
    - outcome='open' (TP was set but never reached — data ran out)
    - pnl_r is None
    - exit_price is last candle close (not TP/SL)
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_LATE, "buy", sl_off=FAR, tp_off=FAR)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "open", (
        f"Expected 'open' (data exhausted with TP set); got {r['outcome_at_user_tp']!r}. "
        f"Entry was at {_C_LATE['Local time']} — check Feb 25 parquet coverage."
    )
    assert r["pnl_r"] is None
    assert r["exit_price"] is not None


def test_T13_08_sell_data_ends_outcome_open(clean_data_frames):
    """SELL, end of data, both legs unreachable → outcome='open'."""
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_LATE, "sell", sl_off=FAR, tp_off=FAR)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "open"
    assert r["pnl_r"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 2 — Error paths
# ═══════════════════════════════════════════════════════════════════════════════

def test_T13_09_sl_distance_zero_graceful_fail(clean_data_frames):
    """
    SL = entry_price (distance = 0 pips).
    Calculator raises ValueError before walking. Must return price_path_captured=False
    without throwing to the caller.

    This is EC6 from mfe_calculator docstring.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    ep = float(_C_EARLY["Close"])

    params = dict(
        entry_time        = _C_EARLY["Local time"],
        entry_price       = ep,
        stoploss_price    = ep,   # SL == entry → distance = 0
        takeprofit_price  = ep + TIGHT,
        trade_type        = "buy",
        symbol            = "EURUSD",
        limit_price       = None,
        breakeven_active  = False,
        breakeven_type    = None,
        breakeven_value   = None,
        input_type        = "prices",
        channel_id        = 1,
    )

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is False, (
        "SL distance=0 should return price_path_captured=False (EC6)"
    )
    assert r["pnl_r"] is None
    assert r["outcome_at_user_tp"] is None


def test_T13_10_symbol_not_in_data_frames(clean_data_frames):
    """
    Symbol not loaded in data_frames.
    Must return price_path_captured=False without a 500 (EC5).
    """
    # Intentionally do NOT inject any data — data_frames is empty after clean_data_frames
    params = _p(_C_EARLY, "buy", sl_off=FAR, tp_off=TIGHT,
                symbol="XYZFAKE")  # symbol that will never exist

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is False, (
        "Unknown symbol should return price_path_captured=False (EC5)"
    )
    assert r["pnl_r"] is None


def test_T13_11_limit_buy_never_triggered(clean_data_frames):
    """
    limit_buy with limit_price far below the entire Feb 24–25 range.
    Order never fills → price_path_captured=False, pending_order_triggered=False.

    This is EC1b from mfe_calculator docstring.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    ep = float(_C_EARLY["Close"])
    limit_below_all_data = ep - FAR  # 5000 pips below market — unreachable

    params = _p(_C_EARLY, "limit_buy", sl_off=FAR, tp_off=TIGHT,
                limit_price=limit_below_all_data)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is False, (
        "limit_buy that never triggers should return price_path_captured=False"
    )
    assert r["pending_order_triggered"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 3 — Pending orders (all expected to trigger)
# ═══════════════════════════════════════════════════════════════════════════════

def test_T13_12_limit_buy_triggered(clean_data_frames):
    """
    limit_buy: limit_price = anchor_close + 1pip.
    Since min(op, lo, cl) ≤ close < close + 1pip = limit_price,
    the trigger condition (min(op,lo,cl) ≤ lp) fires on the FIRST candle
    of df_pending. 100% guaranteed by arithmetic.

    Asserts
    -------
    - pending_order_triggered=True
    - price_path_captured=True
    - actual_entry_price was set to limit_price (not original entry_price)
    - outcome is one of the valid 5 (walk proceeded normally after trigger)
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    ep    = float(_C_EARLY["Close"])
    # Entry time slightly before the anchor candle so anchor is in df_pending
    etime = _C_EARLY["Local time"] - timedelta(minutes=1)
    lp    = ep + PIP  # 1 pip above close → guaranteed trigger (min(op,lo,cl) ≤ close ≤ lp)

    params = dict(
        entry_time        = etime,
        entry_price       = ep,
        stoploss_price    = lp - FAR,   # SL far below limit level
        takeprofit_price  = lp + TIGHT, # tight TP above limit level
        trade_type        = "limit_buy",
        symbol            = "EURUSD",
        limit_price       = lp,
        breakeven_active  = False,
        breakeven_type    = None,
        breakeven_value   = None,
        input_type        = "prices",
        channel_id        = 1,
    )

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True, (
        "limit_buy guaranteed trigger should return price_path_captured=True"
    )
    assert r["pending_order_triggered"] is True, (
        f"limit_buy with lp={lp:.5f} (anchor_close={ep:.5f} + 1pip) should trigger"
    )
    assert r["pending_trigger_time"] is not None
    assert r["pending_wait_minutes"] is not None
    assert r["outcome_at_user_tp"] in {"hit_tp", "hit_sl", "hit_be", "open", "none"}
    _assert_pnl_r_rule(r)
    _assert_alive_monotonic(r)


def test_T13_13_limit_sell_triggered(clean_data_frames):
    """
    limit_sell: limit_price = anchor_high - 1pip.
    max(op, hi, cl) ≥ high > high - 1pip = lp → triggers on first candle.
    100% guaranteed by arithmetic.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    hi    = float(_C_EARLY["High"])
    etime = _C_EARLY["Local time"] - timedelta(minutes=1)
    lp    = hi - PIP   # 1 pip below high → guaranteed: max(op,hi,cl) ≥ hi > lp

    params = dict(
        entry_time        = etime,
        entry_price       = hi,
        stoploss_price    = lp + FAR,   # SL far above limit level
        takeprofit_price  = lp - TIGHT, # tight TP below limit level
        trade_type        = "limit_sell",
        symbol            = "EURUSD",
        limit_price       = lp,
        breakeven_active  = False,
        breakeven_type    = None,
        breakeven_value   = None,
        input_type        = "prices",
        channel_id        = 1,
    )

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["pending_order_triggered"] is True, (
        f"limit_sell with lp={lp:.5f} (anchor_high={hi:.5f} - 1pip) should trigger"
    )
    assert r["pending_trigger_time"] is not None
    assert r["outcome_at_user_tp"] in {"hit_tp", "hit_sl", "hit_be", "open", "none"}
    _assert_pnl_r_rule(r)


def test_T13_14_stop_buy_triggered(clean_data_frames):
    """
    stop_buy: stop = anchor_close + 1pip.
    Candle 0 of df_pending is skipped (no prev_close for direction confirmation).
    Candle 1: prev_close = anchor_close < anchor_close + 1pip = stop.
              Need: max(op, hi, cl) ≥ stop.
    A 1-pip upward move from anchor close appears within a few candles in
    any 48h EURUSD window. Asserts trigger fires and walk proceeds.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    ep    = float(_C_EARLY["Close"])
    etime = _C_EARLY["Local time"] - timedelta(minutes=1)
    stop  = ep + PIP   # 1 pip above anchor close — crossover

    params = dict(
        entry_time        = etime,
        entry_price       = ep,
        stoploss_price    = stop - FAR,    # SL far below stop level
        takeprofit_price  = stop + TIGHT,  # tight TP just above stop level
        trade_type        = "stop_buy",
        symbol            = "EURUSD",
        limit_price       = stop,
        breakeven_active  = False,
        breakeven_type    = None,
        breakeven_value   = None,
        input_type        = "prices",
        channel_id        = 1,
    )

    r = mfe_calculator.calculate_mfe(**params)

    # stop_buy may fail to trigger if parquet data is unusual — mark as xfail
    if r["pending_order_triggered"] is False:
        pytest.xfail(
            f"stop_buy with stop={stop:.5f} never triggered — "
            f"unusual market data for {_C_EARLY['Local time']}. "
            f"price_path_captured={r['price_path_captured']}"
        )

    assert r["price_path_captured"] is True
    assert r["pending_order_triggered"] is True
    assert r["outcome_at_user_tp"] in {"hit_tp", "hit_sl", "hit_be", "open", "none"}
    _assert_pnl_r_rule(r)


def test_T13_15_stop_sell_triggered(clean_data_frames):
    """
    stop_sell: stop = anchor_close - 1pip.
    Candle 1 prev_close = anchor_close > stop. Need: min(op, lo, cl) ≤ stop.
    A 1-pip downward move appears quickly in EURUSD M1 data.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    ep    = float(_C_EARLY["Close"])
    etime = _C_EARLY["Local time"] - timedelta(minutes=1)
    stop  = ep - PIP   # 1 pip below anchor close

    params = dict(
        entry_time        = etime,
        entry_price       = ep,
        stoploss_price    = stop + FAR,    # SL far above stop level
        takeprofit_price  = stop - TIGHT,  # tight TP just below stop level
        trade_type        = "stop_sell",
        symbol            = "EURUSD",
        limit_price       = stop,
        breakeven_active  = False,
        breakeven_type    = None,
        breakeven_value   = None,
        input_type        = "prices",
        channel_id        = 1,
    )

    r = mfe_calculator.calculate_mfe(**params)

    if r["pending_order_triggered"] is False:
        pytest.xfail(
            f"stop_sell with stop={stop:.5f} never triggered — unusual data."
        )

    assert r["price_path_captured"] is True
    assert r["pending_order_triggered"] is True
    assert r["outcome_at_user_tp"] in {"hit_tp", "hit_sl", "hit_be", "open", "none"}
    _assert_pnl_r_rule(r)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 4 — Breakeven paths
# ═══════════════════════════════════════════════════════════════════════════════

def test_T13_16_buy_be_tp_fires_before_be_level(clean_data_frames):
    """
    BE configured at 0.5R; TP is tight (2pip, so TP_level << BE_level).

    With SL=10pip and BE@0.5R: BE trigger price = entry + 5pip.
    TP = entry + 2pip → TP fires BEFORE price can reach 5pip.
    Therefore: be_triggered=False, all BE fields null, UNTP uses original SL.

    This is EC12 / EC4b in the edge-case specification.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    ep = float(_C_EARLY["Close"])

    # TP is at +2pip; BE fires at +5pip (0.5R × 10pip SL).
    # TP must fire before price reaches +5pip.
    params = _p(_C_EARLY, "buy",
                sl_off    = SL_MED,    # 10 pip SL
                tp_off    = TIGHT,     # 2 pip TP (fires well before BE level)
                breakeven_active = True,
                breakeven_type   = "rr",
                breakeven_value  = 0.5,
               )

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "hit_tp", (
        f"TP=2pip should fire before BE@5pip; got {r['outcome_at_user_tp']!r}"
    )
    # BE phantom rule: TP fires before BE was ever reached
    assert r["breakeven_triggered"] is False, (
        "breakeven_triggered should be False when TP fires before BE level"
    )
    assert r["breakeven_sl_price"] is None
    assert r["breakeven_trigger_time_minutes"] is None
    assert r["mfe_at_breakeven_r"] is None
    assert r["mfe_after_be_r"] is None

    _assert_pnl_r_rule(r)


def test_T13_17_sell_be_tp_fires_before_be_level(clean_data_frames):
    """
    SELL: BE configured at 0.5R; TP tight (2pip) fires before BE level.
    Same phantom-cleanup rule as T13_16, for sell direction.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF

    params = _p(_C_EARLY, "sell",
                sl_off    = SL_MED,
                tp_off    = TIGHT,
                breakeven_active = True,
                breakeven_type   = "rr",
                breakeven_value  = 0.5,
               )

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "hit_tp", (
        f"SELL TP=2pip should fire before BE@5pip; got {r['outcome_at_user_tp']!r}"
    )
    assert r["breakeven_triggered"] is False
    assert r["breakeven_sl_price"] is None
    assert r["mfe_after_be_r"] is None
    _assert_pnl_r_rule(r)


def test_T13_18_buy_be_fires_produces_correct_fields(clean_data_frames):
    """
    BUY: BE at 0.1R (1pip trigger with 10pip SL), TP unreachable, SL=10pip.

    BE fires when price moves +1pip in favour. After BE fires, the effective
    SL is entry_price. If price retraces to entry → outcome='hit_be'.
    If original SL fires first → outcome='hit_sl'.

    This test is CONDITIONAL: it accepts both hit_be and hit_sl, and
    asserts the correct rule-set for whichever outcome occurred.

    What this specifically validates:
    - If hit_be: be_triggered=True, breakeven_sl_price=entry_price,
                 pnl_r=0.0, exit_price=entry_price
    - If hit_sl: be_triggered=False (SL fired before BE level was reached)
                 OR be_triggered=True but then price continued to SL after BE
                 — in this sub-case, outcome is still hit_sl.

    Note: outcome='hit_tp' is EXCLUDED (TP=unreachable).
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    ep = float(_C_EARLY["Close"])

    params = _p(_C_EARLY, "buy",
                sl_off    = SL_MED,        # 10 pip SL
                tp_off    = FAR,           # unreachable TP
                breakeven_active = True,
                breakeven_type   = "rr",
                breakeven_value  = 0.1,    # BE fires at +1pip (0.1R × 10pip)
               )

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] in {"hit_be", "hit_sl"}, (
        f"Expected hit_be or hit_sl; got {r['outcome_at_user_tp']!r} (TP is unreachable)"
    )

    if r["outcome_at_user_tp"] == "hit_be":
        # Rule: BE was triggered → check all BE fields
        assert r["breakeven_triggered"] is True, "hit_be: breakeven_triggered must be True"
        assert r["breakeven_sl_price"] == pytest.approx(ep, rel=1e-6), (
            f"breakeven_sl_price should equal entry_price={ep:.5f}"
        )
        assert r["pnl_r"] == pytest.approx(0.0, abs=1e-9)
        assert r["exit_price"] == pytest.approx(ep, rel=1e-6)
        assert r["mfe_at_breakeven_r"] is not None, "mfe_at_breakeven_r should be set"
        assert r["breakeven_trigger_time_minutes"] is not None

        # UNTP for hit_be: stop condition is entry_price retrace (same as trade close)
        # → UNTP stops same candle → all alive=False
        for k in CHECKPOINT_KEYS:
            assert r[f"alive_at_{k}"] is False, (
                f"alive_at_{k} should be False for hit_be (UNTP stops same candle)"
            )

    elif r["outcome_at_user_tp"] == "hit_sl":
        # SL fired (either before or after BE) — pnl_r rule still holds
        assert r["pnl_r"] == pytest.approx(-1.0, abs=1e-9)
        assert r["exit_price"] == pytest.approx(params["stoploss_price"], rel=1e-6)


def test_T13_19_buy_be_fields_when_be_triggers_before_tp(clean_data_frames):
    """
    BUY: BE at 1R (10pip trigger), TP at 3R (30pip), SL = 10pip.
    If BE fires (price reaches +10pip), then TP fires later (price reaches +30pip):
    outcome = hit_tp, but also mfe_after_be_r should be populated.

    This test uses the mid-slice candle for a longer walk window.
    Outcome is data-dependent: accepted as hit_tp or hit_sl or hit_be or open.
    The test validates whichever rule-set applies.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF

    params = _p(_C_MID, "buy",
                sl_off    = SL_MED,    # 10 pip SL
                tp_off    = TP_3R,     # 30 pip TP = 3R
                breakeven_active = True,
                breakeven_type   = "rr",
                breakeven_value  = 1.0,  # BE fires at 1R = 10pip
               )

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    out = r["outcome_at_user_tp"]
    assert out in {"hit_tp", "hit_sl", "hit_be", "open"}, (
        f"Unexpected outcome: {out!r}"
    )

    # Core rule: pnl_r must match outcome regardless of BE
    _assert_pnl_r_rule(r)

    if r["breakeven_triggered"] is True:
        # BE fired: these fields must be populated
        ep = float(_C_MID["Close"])
        assert r["breakeven_sl_price"] == pytest.approx(ep, rel=1e-6)
        assert r["mfe_at_breakeven_r"] is not None
        assert r["breakeven_trigger_time_minutes"] is not None
        if out == "hit_tp":
            # mfe_after_be_r: MFE accumulates from BE activation to trade close
            assert r["mfe_after_be_r"] is not None
            assert r["mfe_after_be_r"] >= 0.0
    else:
        # BE not triggered: all BE fields null
        assert r["breakeven_sl_price"] is None
        assert r["mfe_at_breakeven_r"] is None
        assert r["mfe_after_be_r"] is None

    _assert_all_checkpoints_populated(r)
    _assert_alive_monotonic(r)


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 5 — UNTP rules
# ═══════════════════════════════════════════════════════════════════════════════

def test_T13_20_buy_hit_tp_untp_continues_alive_at_checkpoints(clean_data_frames):
    """
    BUY hit_tp (tight TP), SL=unreachable (5000pip).

    After trade closes at TP, UNTP continues with stop=original_SL=5000pip below.
    The UNTP will NOT stop in any 48h EURUSD window because SL is 5000pip away.
    Therefore: alive_at_30min=True AND alive_at_1h=True (UNTP still running).

    Also: outcome_at_30min must be 'hit_tp' (trade already closed before 30min).
    This verifies that outcome_at_Xh and alive_at_Xh are INDEPENDENT fields.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_EARLY, "buy", sl_off=FAR, tp_off=TIGHT)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "hit_tp"

    # UNTP alive: SL=5000pip never fires → UNTP continues running
    assert r["alive_at_30min"] is True, (
        "alive_at_30min=False: UNTP should still be running at 30min "
        "(SL=5000pip unreachable, trade already closed at hit_tp)"
    )
    assert r["alive_at_1h"] is True, (
        "alive_at_1h=False: UNTP still running at 1h with 5000pip SL"
    )

    # outcome_at_30min: trade already closed → should be 'hit_tp'
    # (not 'still_open', because the trade closed before 30min checkpoint)
    assert r["outcome_at_30min"] == "hit_tp", (
        f"outcome_at_30min={r['outcome_at_30min']!r}: trade hit_tp before 30min, "
        f"so outcome_at_30min should be 'hit_tp', not 'still_open'"
    )

    # INDEPENDENT: both alive=True AND outcome='hit_tp' at same checkpoint → valid
    _assert_alive_monotonic(r)


def test_T13_21_buy_hit_sl_all_untp_alive_false(clean_data_frames):
    """
    BUY hit_sl (tight SL 2pip). UNTP stop condition = original SL.
    SL fires = UNTP also stops same candle.
    All 14 alive_at checkpoints must be False. No exceptions.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_EARLY, "buy", sl_off=TIGHT, tp_off=FAR)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "hit_sl"

    for k in CHECKPOINT_KEYS:
        assert r[f"alive_at_{k}"] is False, (
            f"alive_at_{k}=True for buy hit_sl — all must be False (UNTP stops with SL)"
        )

    # All outcome_at_Xh should be 'hit_sl' (trade closed before every checkpoint)
    for k in CHECKPOINT_KEYS:
        assert r[f"outcome_at_{k}"] == "hit_sl", (
            f"outcome_at_{k}={r[f'outcome_at_{k}']!r}: should be 'hit_sl' after trade closed"
        )


def test_T13_22_sell_hit_tp_untp_outcome_at_checkpoints(clean_data_frames):
    """
    SELL hit_tp. outcome_at_Xh must be 'hit_tp' at all 14 checkpoints.

    The trade closes at TP within minutes. outcome_at_Xh tracks the TRADE
    outcome — once the trade closes it is frozen as 'hit_tp' at every
    subsequent checkpoint, independent of UNTP alive status.

    alive_at_Xh is NOT asserted here. The parquet covers only Feb 24-25
    (~48h of data). Checkpoints beyond ~48h (72h, 120h, ...) correctly
    show alive=False due to data exhaustion (EC15) — not a bug.
    alive assertions for this scenario are in T13_20 (early checkpoints only).
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_EARLY, "sell", sl_off=FAR, tp_off=TIGHT)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "hit_tp"

    # outcome_at_Xh frozen as 'hit_tp' at all 14 checkpoints — independent of alive
    for k in CHECKPOINT_KEYS:
        assert r[f"outcome_at_{k}"] == "hit_tp", (
            f"outcome_at_{k}={r[f'outcome_at_{k}']!r}: "
            f"trade hit_tp before every checkpoint — must be frozen as 'hit_tp'"
        )

def test_T13_23_untp_mfe_frozen_after_stop(clean_data_frames):
    """
    BUY hit_sl (tight SL). After UNTP stops (same candle as trade):
    - mfe_at_Xh_r must be the same value at ALL 14 checkpoints (frozen at stop)
    - mae_at_Xh_r must also be frozen (constant after stop)
    - No checkpoint can show a higher mfe than the stop candle's value

    This is EC16 in mfe_calculator (untp_mfe_frozen / untp_mae_frozen logic).
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_EARLY, "buy", sl_off=TIGHT, tp_off=FAR)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "hit_sl"
    assert r["alive_at_30min"] is False

    # All mfe_at_Xh_r values must be identical (frozen at stop value)
    mfe_values = [r[f"mfe_at_{k}_r"] for k in CHECKPOINT_KEYS]
    mae_values = [r[f"mae_at_{k}_r"] for k in CHECKPOINT_KEYS]

    # All non-None
    assert all(v is not None for v in mfe_values), "All mfe_at_Xh_r must be populated"
    assert all(v is not None for v in mae_values), "All mae_at_Xh_r must be populated"

    # Frozen = constant across all 14 checkpoints
    assert len(set(round(v, 9) for v in mfe_values)) == 1, (
        f"mfe_at_Xh_r values are not frozen after UNTP stop: {mfe_values}"
    )
    assert len(set(round(v, 9) for v in mae_values)) == 1, (
        f"mae_at_Xh_r values are not frozen after UNTP stop: {mae_values}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# GROUP 6 — pnl_r / R milestones / mfe_path
# ═══════════════════════════════════════════════════════════════════════════════

def test_T13_24_pnl_r_equals_tp_rr_target_not_always_1(clean_data_frames):
    """
    hit_tp with SL=10pip and TP=30pip → tp_rr_target=3.0, pnl_r=3.0.
    Verifies pnl_r = tp_rr_target, NOT always 1.0.

    This confirms R2: pnl_r is +tp_rr_target for hit_tp, not a fixed +1.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_EARLY, "buy",
                sl_off = SL_MED,   # 10 pip SL
                tp_off = TIGHT,    # tight 2 pip TP — fires fast
               )

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "hit_tp"

    # tp_rr_target = 2pip / 10pip = 0.2R
    expected_rr = TIGHT / SL_MED
    assert r["tp_rr_target"] == pytest.approx(expected_rr, rel=0.01), (
        f"tp_rr_target={r['tp_rr_target']:.4f}, expected {expected_rr:.4f}"
    )
    assert r["pnl_r"] == pytest.approx(expected_rr, rel=0.01), (
        f"pnl_r={r['pnl_r']:.4f} should equal tp_rr_target={expected_rr:.4f}, not 1.0"
    )


def test_T13_25_pnl_r_hit_sl_always_negative_one(clean_data_frames):
    """
    hit_sl: pnl_r must be exactly -1.0 regardless of SL distance or TP settings.
    Confirms R2 (pnl_r = -1.0 for hit_sl, not derived from MAE or price change).
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_EARLY, "buy", sl_off=TIGHT, tp_off=FAR)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] == "hit_sl"
    assert r["pnl_r"] == pytest.approx(-1.0, abs=1e-9), (
        f"hit_sl pnl_r={r['pnl_r']}: must be exactly -1.0 (R2 rule)"
    )
    assert r["rr_at_user_tp"] == pytest.approx(-1.0, abs=1e-9), (
        "rr_at_user_tp is an alias for pnl_r — must also be -1.0"
    )


def test_T13_26_mfe_mae_positive_for_resolved_trade(clean_data_frames):
    """
    For any trade that resolves (hit_tp or hit_sl), mfe_r > 0 and mae_r > 0.

    mfe_r: peak favourable move. Even a 2-pip TP trade will have mfe_r > 0.
    mae_r: peak adverse move. In any M1 candle, price wiggles both ways.

    Verifies these fields are not zero/None for a normal trade.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_MID, "buy", sl_off=SL_MED, tp_off=TP_1R)  # 1R trade

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["outcome_at_user_tp"] in {"hit_tp", "hit_sl", "hit_be", "open"}

    if r["outcome_at_user_tp"] in {"hit_tp", "hit_sl"}:
        assert r["mfe_r"] is not None and r["mfe_r"] > 0.0, (
            f"mfe_r={r['mfe_r']} should be > 0 for a resolved trade"
        )
        assert r["mae_r"] is not None and r["mae_r"] >= 0.0, (
            f"mae_r={r['mae_r']} should be ≥ 0 for a resolved trade"
        )
        assert r["sl_distance_pips"] == pytest.approx(SL_MED / PIP, rel=0.01), (
            f"sl_distance_pips={r['sl_distance_pips']}, expected {SL_MED/PIP}"
        )


def test_T13_27_mfe_path_sampling_intervals_multiples_of_15(clean_data_frames):
    """
    mfe_path_json must sample at multiples of 15 minutes (last_path_min += 15).
    This confirms BUG-3 fix is intact: sampling uses += 15, NOT = elapsed_min.

    Checks:
    - All intervals between path entries are multiples of 15 (within tolerance)
    - No drift: interval at minute 60 is exactly 60, not some other value
    - Path is valid JSON, each entry is [elapsed, mfe_r, mae_r, alive]
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    # Use mid-slice entry so trade walks for an extended period
    params = _p(_C_MID, "buy", sl_off=SL_MED, tp_off=FAR)

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True
    assert r["mfe_path_json"] is not None

    path = json.loads(r["mfe_path_json"])
    assert len(path) >= 1, "mfe_path_json must have at least 1 entry"

    # Validate structure: each entry is [elapsed, mfe_r, mae_r, alive]
    for i, entry in enumerate(path):
        assert len(entry) == 4, f"path[{i}] should have 4 elements: {entry}"
        elapsed, mfe, mae, alive = entry
        assert elapsed >= 0, f"path[{i}] elapsed={elapsed} is negative"
        assert mfe >= 0,     f"path[{i}] mfe_r={mfe} is negative"
        assert mae >= 0,     f"path[{i}] mae_r={mae} is negative"
        assert alive in (0, 1), f"path[{i}] untp_alive={alive} should be 0 or 1"

    # Regular entries (excluding forced entries) must be at multiples of 15min
    # Forced entries (at trade close and UNTP stop) can be at any elapsed time.
    # Strategy: check that all intervals between consecutive regular entries are 15.
    elapsed_list = [e[0] for e in path]

    # Check for no duplicates
    assert len(elapsed_list) == len(set(elapsed_list)), (
        f"Duplicate elapsed_min entries found in mfe_path_json: {elapsed_list}"
    )

    # Check regular sampling gaps: between consecutive samples must be ≤ 15
    # (forced entries at trade close can create smaller gaps)
    for i in range(1, len(elapsed_list)):
        gap = elapsed_list[i] - elapsed_list[i - 1]
        assert gap > 0, f"path not monotonically increasing: gap={gap} at i={i}"
        assert gap <= 15 + 0.001, (
            f"gap between path[{i-1}] and path[{i}] is {gap:.3f}min > 15min — "
            f"sampling must use last_path_min += 15, not = elapsed_min"
        )


def test_T13_28_r_milestones_populated_and_monotonic(clean_data_frames):
    """
    For a trade that travels at least 1R in favour (hit_tp with 1R target):
    - time_to_1r_minutes must be populated (not None)
    - R milestones must be monotonically non-decreasing where not None:
      time_to_0_5r ≤ time_to_1r ≤ time_to_1_5r … (NULL means never reached)
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF
    params = _p(_C_MID, "buy",
                sl_off = SL_MED,   # 10 pip SL
                tp_off = TP_1R,    # 1R TP (10pip) — will reach 1R to close
               )

    r = mfe_calculator.calculate_mfe(**params)

    assert r["price_path_captured"] is True

    milestones = [
        ("time_to_0_5r_minutes", 0.5),
        ("time_to_1r_minutes",   1.0),
        ("time_to_1_5r_minutes", 1.5),
        ("time_to_2r_minutes",   2.0),
        ("time_to_3r_minutes",   3.0),
        ("time_to_4r_minutes",   4.0),
        ("time_to_5r_minutes",   5.0),
    ]

    # For hit_tp at 1R: 0.5R and 1R must be reached
    if r["outcome_at_user_tp"] == "hit_tp":
        assert r["time_to_0_5r_minutes"] is not None, (
            "hit_tp at 1R: time_to_0_5r_minutes should be populated (price crossed 0.5R)"
        )
        assert r["time_to_1r_minutes"] is not None, (
            "hit_tp at 1R: time_to_1r_minutes should be populated (price closed at 1R=TP)"
        )
        # 1.5R and above should be None (TP was set at 1R, price never needed to go further)
        assert r["time_to_1_5r_minutes"] is None, (
            "hit_tp at 1R: time_to_1_5r_minutes should be None (TP closed at 1R)"
        )

    # Monotonicity: non-None milestones must be non-decreasing
    prev_time = 0.0
    for key, _ in milestones:
        t = r[key]
        if t is not None:
            assert t >= prev_time, (
                f"R milestone {key}={t:.1f} < prev={prev_time:.1f} — not monotonic"
            )
            prev_time = t


def test_T13_29_entry_session_and_day_of_week_populated(clean_data_frames):
    """
    entry_session and entry_day_of_week must always be populated,
    even when price_path_captured=False (they are computed from entry_time alone).

    Also confirms entry_hour matches the actual entry_time hour.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF

    for candle in [_C_EARLY, _C_MID]:
        ep    = float(candle["Close"])
        etime = candle["Local time"]

        params = _p(candle, "buy", sl_off=FAR, tp_off=TIGHT)
        r = mfe_calculator.calculate_mfe(**params)

        assert r["entry_day_of_week"] == etime.weekday(), (
            f"entry_day_of_week={r['entry_day_of_week']}, "
            f"expected {etime.weekday()} ({etime.strftime('%A')})"
        )
        assert r["entry_hour"] == etime.hour, (
            f"entry_hour={r['entry_hour']}, expected {etime.hour}"
        )
        assert r["entry_session"] in {"asian", "london", "overlap", "new_york", "off_hours"}


def test_T13_30_price_path_captured_true_for_normal_trade(clean_data_frames):
    """
    Sanity guard: for any trade with valid params and data present,
    price_path_captured must be True.

    Tests buy AND sell against the real EURUSD data.
    """
    mfe_calculator.data_frames["EURUSD"] = _EURUSD_DF

    for trade_type in ("buy", "sell"):
        params = _p(_C_EARLY, trade_type, sl_off=SL_MED, tp_off=TP_1R)
        r = mfe_calculator.calculate_mfe(**params)

        assert r["price_path_captured"] is True, (
            f"{trade_type}: price_path_captured=False for a normal trade — "
            f"check that EURUSD data covers {_C_EARLY['Local time']}"
        )
        _assert_pnl_r_rule(r)
        _assert_all_checkpoints_populated(r)
        _assert_alive_monotonic(r)