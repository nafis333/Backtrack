"""
utils/mfe_calculator.py
-----------------------
Runs at trade-save time. Walks the parquet price data from entry and runs
TWO independent monitors simultaneously on every candle:

  TRADE WALK  — resolves the actual trade. Closes on the first trigger:
                  1. TP hit  → exit_price=takeprofit_price, pnl_r=+tp_rr_target
                  2. SL hit  → exit_price=stoploss_price,   pnl_r=-1.0
                  3. BE-entry retrace → exit_price=entry_price, pnl_r=0.0

  UNTP WALK   — runs fully independently. Never affects pnl_r.
                Stop condition depends on whether BE actually triggered:
                  BE not triggered → stops when original SL is hit
                  BE triggered     → stops when entry price is retraced
                Cap: 504h (21 days)

Both walks share the same candle loop and the same be_triggered flag.
They naturally co-terminate on SL/BE hits. They diverge only on TP —
trade closes, UNTP keeps running.

Edge cases handled
------------------
EC1  limit_buy/limit_sell: check from candle 0 — no prev_close needed
EC2  stop_buy/stop_sell:   require prev_close to confirm direction crossover;
     naturally skips candle 0 and prevents triggering when already at level
EC3  pending trigger on last candle → df_walk empty → graceful fail
EC4  no candle data after entry/trigger → explicit check before walk
EC5  symbol not in data_frames → ValueError → price_path_captured=False
EC6  SL distance zero → explicit ValueError before walk
EC7  single-candle trade → handled; mfe_path always gets at least 1 entry
EC8  trade resolves before 30min → all 14 snapshots frozen at resolution
EC9  data ends before resolution → last_close fallback, outcome=open/none
EC10 BE configured but never triggered → UNTP uses original SL stop only,
     NOT entry retrace (entry retrace is only a stop if BE actually fired)
EC11 sell dip: measured as price ABOVE entry, not below
EC12 BE at very high R → if TP fires first, be_triggered stays False; correct
EC13 mfe_after_be stops accumulating once trade_fully_closed
EC14 mfe_path_json: deduplicate forced entries at the same elapsed_min
EC15 data ended before all snapshots — post-walk fallback sets alive=False
EC16 UNTP mfe/mae frozen at stop: when untp_stopped fires, peak_mfe_pips
     and peak_mae_pips are captured into untp_mfe_frozen / untp_mae_frozen.
     All not-yet-recorded snapshots are backfilled immediately with the
     frozen value (alive=False), so later candle movement cannot inflate
     mfe_at_Xh_r after the UNTP walk has already stopped. The immediate
     backfill also triggers the early-exit on the very next iteration,
     avoiding unnecessary walking of the remaining cap window.

Public API
----------
calculate_mfe(...) → dict with keys matching Trade column names exactly.
On any error: returns price_path_captured=False with all numeric fields None.
"""

import json
import logging
from data_loader import data_frames

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

# 14 checkpoints: 30min → 21 days
CHECKPOINT_MINUTES = [30, 60, 120, 240, 480, 720, 1440, 2880, 4320, 7200,
                      10080, 14400, 20160, 30240]
CHECKPOINT_KEYS    = ["30min", "1h", "2h", "4h", "8h", "12h",
                      "24h", "48h", "72h", "120h", "168h",
                      "240h", "336h", "504h"]

UNTP_CAP_MINUTES  = 30240        # 504h = 21 days
PATH_INTERVAL_MIN = 15
R_MILESTONES      = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0]
PENDING_TYPES     = {"limit_buy", "limit_sell", "stop_buy", "stop_sell"}


# ── Helpers ──────────────────────────────────────────────────────────────────

# Bug 3 Fix: import pip sizes from the single authoritative source (pip_utils.py)
# so mfe_calculator never silently diverges when new symbols are added.
# A local fallback is kept so the module can be imported in unit tests or CLI
# contexts where utils/ may not be on sys.path, but in normal Flask operation
# the try branch will always succeed.
try:
    from utils.pip_utils import get_pip_size as _get_pip_size
except (ImportError, AttributeError):
    logger.warning(
        "mfe_calculator: could not import get_pip_size from utils.pip_utils — "
        "using local fallback. Ensure this stays in sync with pip_utils.py."
    )
    def _get_pip_size(symbol: str) -> float:  # type: ignore[misc]
        """Local fallback — MUST stay in sync with utils/pip_utils.py."""
        sym = symbol.upper()
        if sym == "XAUUSD":             return 0.1
        if sym == "XAGUSD":             return 0.01
        if sym in {"NAS100", "US30"}:   return 1.0
        if sym in {"USOIL", "UKOIL"}:   return 0.1
        return 0.01 if "JPY" in sym else 0.0001


def _classify_session(hour: int) -> str:
    if 0  <= hour <= 7:  return "asian"
    if 8  <= hour <= 12: return "london"
    if 13 <= hour <= 16: return "overlap"
    if 17 <= hour <= 20: return "new_york"
    return "off_hours"


def _compute_streak(channel_id: int) -> int:
    """Consecutive win/loss streak in channel at save time.

    Scoring:
      hit_tp               → +1  (win)
      hit_sl               → -1  (loss)
      hit_be / open / none → skip (neutral — does not break or extend streak)

    Ordered by entry_time DESC so re-saves and out-of-order imports do not
    corrupt the streak walk. (saved_at order would place a re-saved old trade
    at position 0 and break the streak incorrectly.)
    """
    try:
        from db import Trade
        recent = (
            Trade.query
            .filter_by(channel_id=channel_id)
            .order_by(Trade.entry_time.desc())
            .all()
        )
        streak      = 0
        streak_sign = None
        for t in recent:
            o = t.outcome_at_user_tp
            if o == "hit_tp":
                sign = 1
            elif o == "hit_sl":
                sign = -1
            else:
                # hit_be / open / none — neutral, skip without breaking streak
                continue
            if streak_sign is None:
                streak_sign = sign
                streak      = sign
            elif sign == streak_sign:
                streak += sign
            else:
                break
        return streak
    except Exception:
        return 0


def _empty_result() -> dict:
    """Fully-keyed dict with all computed fields as None (price_path_captured=False)."""
    result: dict = {"price_path_captured": False}
    for key in [
        "input_type",
        "tp_rr_target", "tp_pips_target",
        "pending_trigger_time", "pending_wait_minutes", "pending_order_triggered",
        "sl_distance_pips",
        "mfe_pips", "mfe_r", "mfe_at_close_pips", "mfe_at_close_r",
        "time_to_mfe_minutes",
        "mae_pips", "mae_r", "time_to_mae_minutes",
        "retracement_from_mfe_pips", "retracement_from_mfe_r",
        "exit_price", "candles_to_resolution",
        "dip_pips", "dip_time_minutes", "dip_occurred",
        "outcome_at_user_tp", "pnl_r", "rr_at_user_tp",
        "time_to_resolution_minutes", "tp_was_reached",
        "time_to_tp_minutes", "peak_rr_at_close",
        "breakeven_triggered", "breakeven_sl_price",
        "breakeven_trigger_time_minutes",
        "mfe_at_breakeven_pips", "mfe_at_breakeven_r",
        "mfe_after_be_pips", "mfe_after_be_r",
        "time_to_0_5r_minutes", "time_to_1r_minutes", "time_to_1_5r_minutes",
        "time_to_2r_minutes", "time_to_3r_minutes", "time_to_4r_minutes",
        "time_to_5r_minutes",
        "first_candle_direction", "consecutive_adverse_candles",
        "avg_candle_size_pips_at_entry", "channel_streak_at_save",
        "entry_day_of_week", "entry_hour", "entry_session",
        "mfe_path_json",
    ]:
        result[key] = None
    for key in CHECKPOINT_KEYS:
        result[f"mfe_at_{key}_r"]   = None
        result[f"mae_at_{key}_r"]   = None
        result[f"outcome_at_{key}"] = None
        result[f"alive_at_{key}"]   = None
    return result


# ── Public entry point ───────────────────────────────────────────────────────

def calculate_mfe(
    entry_time,
    entry_price,
    stoploss_price,
    takeprofit_price,
    trade_type,
    symbol,
    limit_price,
    breakeven_active,
    breakeven_type,
    breakeven_value,
    input_type,
    channel_id,
) -> dict:
    """
    Walk price data and return a dict whose keys match Trade column names.
    On any error: returns dict with price_path_captured=False, all computed
    fields None. Trade still saves cleanly.
    """
    try:
        return _run_calculation(
            entry_time, entry_price, stoploss_price, takeprofit_price,
            trade_type, symbol, limit_price, breakeven_active,
            breakeven_type, breakeven_value, input_type, channel_id,
        )
    except Exception as exc:
        logger.exception("mfe_calculator failed for %s %s: %s", symbol, trade_type, exc)
        result = _empty_result()
        result["input_type"] = input_type
        try:
            result["entry_day_of_week"] = entry_time.weekday()
            result["entry_hour"]        = entry_time.hour
            result["entry_session"]     = _classify_session(entry_time.hour)
        except Exception:
            pass
        return result


# ── Core calculation ─────────────────────────────────────────────────────────

def _run_calculation(
    entry_time,
    entry_price,
    stoploss_price,
    takeprofit_price,
    trade_type,
    symbol,
    limit_price,
    breakeven_active,
    breakeven_type,
    breakeven_value,
    input_type,
    channel_id,
) -> dict:

    sym_key    = symbol.upper()
    pip_size   = _get_pip_size(sym_key)
    base_trade = "buy" if "buy" in trade_type else "sell"
    is_pending = trade_type in PENDING_TYPES

    # ── 1. Fetch data ─────────────────────────────────────────────────────────
    # EC5: unknown symbol → ValueError → outer except → price_path_captured=False
    if sym_key not in data_frames:
        raise ValueError(f"No parquet data loaded for symbol: {sym_key}")
    df = data_frames[sym_key]

    # ── 2. Pending order: walk to trigger ────────────────────────────────────
    #
    # EC1 — limit orders check from candle 0:
    #   limit_buy/limit_sell don't need a previous close for context — any
    #   candle whose low (buy) or high (sell) touches the limit price is a fill.
    #
    # EC2 — stop orders confirm a direction crossover via prev_close:
    #   stop_buy:  prev_close must be BELOW lp, then price breaks ABOVE.
    #              Using `prev_close is not None` means candle 0 is skipped
    #              (no direction to confirm yet), which also prevents a false
    #              trigger when price is already at or above the level.
    #   stop_sell: symmetric — prev_close must be ABOVE lp.
    #
    # EC3 — pending trigger on last available candle:
    #   After trigger, df[Local time > ct] is empty. Caught below.

    actual_entry_time       = entry_time
    actual_entry_price      = float(entry_price)
    pending_trigger_time    = None
    pending_wait_minutes    = None
    pending_order_triggered = None if not is_pending else False

    if is_pending:
        lp = float(limit_price)
        df_pending = (
            df[df["Local time"] > entry_time]
            .sort_values("Local time")
            .reset_index(drop=True)
        )
        triggered  = False
        prev_close = None   # only used by stop types for direction confirmation

        for _, row in df_pending.iterrows():
            hi, lo, cl, op = row["High"], row["Low"], row["Close"], row["Open"]
            ct = row["Local time"]

            if trade_type == "limit_buy":
                # EC1: check every candle; min(op,lo,cl) handles gap-opens below limit
                triggered = min(op, lo, cl) <= lp

            elif trade_type == "limit_sell":
                # EC1: check every candle; max(op,hi,cl) handles gap-opens above limit
                triggered = max(op, hi, cl) >= lp

            elif trade_type == "stop_buy":
                # EC2: prev_close < lp confirms price was below level (crossover up)
                #      prev_close is not None naturally skips candle 0
                triggered = (prev_close is not None
                             and prev_close < lp
                             and max(op, hi, cl) >= lp)

            elif trade_type == "stop_sell":
                # EC2: prev_close > lp confirms price was above level (crossover down)
                triggered = (prev_close is not None
                             and prev_close > lp
                             and min(op, lo, cl) <= lp)
            else:
                triggered = False

            if triggered:
                actual_entry_time       = ct
                actual_entry_price      = lp
                pending_trigger_time    = ct
                pending_wait_minutes    = (ct - entry_time).total_seconds() / 60.0
                pending_order_triggered = True
                break

            prev_close = cl  # stop types use this; harmless for limit types

        if not triggered:
            # Order never filled in available data — graceful failure
            result = _empty_result()
            result.update({
                "input_type":               input_type,
                "pending_order_triggered":  False,
                "price_path_captured":      False,
                "entry_day_of_week":        entry_time.weekday(),
                "entry_hour":               entry_time.hour,
                "entry_session":            _classify_session(entry_time.hour),
                "channel_streak_at_save":   _compute_streak(channel_id),
            })
            return result

    # ── 3. Pre-compute invariants ─────────────────────────────────────────────
    original_sl      = float(stoploss_price)
    sl_distance_pips = abs(actual_entry_price - original_sl) / pip_size

    # EC6: zero SL distance → guard before any division
    if sl_distance_pips == 0:
        raise ValueError("SL distance is zero — entry_price equals stoploss_price")

    has_tp = takeprofit_price is not None
    if has_tp:
        tp_pips_target = abs(actual_entry_price - float(takeprofit_price)) / pip_size
        tp_rr_target   = tp_pips_target / sl_distance_pips
        actual_tp      = float(takeprofit_price)
    else:
        tp_pips_target = None
        tp_rr_target   = None
        actual_tp      = None

    # Breakeven trigger price
    # EC12: be_trigger_price is computed correctly for any R value; if TP fires
    #       before price reaches be_trigger_price, be_triggered stays False.
    be_trigger_price = None
    if breakeven_active and breakeven_value:
        bv           = float(breakeven_value)
        initial_risk = sl_distance_pips * pip_size
        if breakeven_type == "rr":
            be_trigger_price = (
                actual_entry_price + initial_risk * bv
                if base_trade == "buy"
                else actual_entry_price - initial_risk * bv
            )
        elif breakeven_type == "pips":
            be_trigger_price = (
                actual_entry_price + bv * pip_size
                if base_trade == "buy"
                else actual_entry_price - bv * pip_size
            )

    # ── 4. Slice working data ─────────────────────────────────────────────────
    df_walk = (
        df[df["Local time"] > actual_entry_time]
        .sort_values("Local time")
        .reset_index(drop=True)
    )

    # EC3 + EC4: empty df_walk — pending trigger on last candle, or no data at all
    if df_walk.empty:
        if is_pending and pending_order_triggered:
            logger.warning(
                "mfe_calculator [%s]: pending order triggered on last candle — "
                "no walk data available after trigger", sym_key
            )
        else:
            logger.warning(
                "mfe_calculator [%s]: no candle data after entry_time", sym_key
            )
        result = _empty_result()
        result.update({
            "input_type":               input_type,
            "pending_order_triggered":  pending_order_triggered,
            "pending_trigger_time":     pending_trigger_time,
            "pending_wait_minutes":     pending_wait_minutes,
            "price_path_captured":      False,
            "entry_day_of_week":        entry_time.weekday(),
            "entry_hour":               entry_time.hour,
            "entry_session":            _classify_session(entry_time.hour),
            "channel_streak_at_save":   _compute_streak(channel_id),
        })
        return result

    # Volatility context: avg H-L range over 10 candles before entry
    df_pre = (
        df[df["Local time"] <= actual_entry_time]
        .sort_values("Local time")
        .tail(10)
    )
    avg_candle_size_pips = (
        df_pre.apply(lambda r: (r["High"] - r["Low"]) / pip_size, axis=1).mean()
        if len(df_pre) >= 1 else None
    )

    # ── 5. Session / day context ──────────────────────────────────────────────
    entry_day_of_week = actual_entry_time.weekday()
    entry_hour        = actual_entry_time.hour
    entry_session     = _classify_session(entry_hour)

    # ── 6. Initialise walk state ──────────────────────────────────────────────

    # Shared MFE / MAE peaks — accumulate every candle through UNTP cap.
    # Trade walk freezes a snapshot at close; UNTP walk keeps going.
    peak_mfe_pips = 0.0
    peak_mae_pips = 0.0
    peak_mfe_time = actual_entry_time
    peak_mae_time = actual_entry_time

    # R milestones — trade walk only (gated on not trade_fully_closed)
    r_milestone_times: dict = {r: None for r in R_MILESTONES}

    # ── BE state — shared between both walks ──────────────────────────────────
    # EC10: be_triggered=False means UNTP stop condition is original SL only.
    #       Entry retrace is NOT a UNTP stop unless BE actually fired.
    be_triggered      = False
    current_sl        = original_sl   # reassigned to actual_entry_price when BE fires
    be_trigger_min    = None
    mfe_at_be_pips    = None
    mfe_at_be_r_val   = None
    peak_mfe_after_be = 0.0           # EC13: accumulates until trade_fully_closed

    # ── Dip state — trade walk only ───────────────────────────────────────────
    # EC11: for sell trades, adverse = price going ABOVE entry before first
    #       favourable move. The dip code uses base_trade to handle this.
    dip_ended     = False
    peak_dip_pips = 0.0
    peak_dip_time = actual_entry_time

    # ── Entry quality — trade walk only ───────────────────────────────────────
    first_candle_direction = None
    consecutive_adverse    = 0
    counting_adverse       = True

    # ── TRADE walk state ──────────────────────────────────────────────────────
    trade_fully_closed    = False
    trade_outcome         = None
    exit_price            = None
    resolution_min        = None
    resolution_candle_time = None   # Bug 4 fix: track exact candle when trade resolved
    pnl_r_final           = None
    peak_rr_at_close_val  = None
    candles_to_resolution = None
    mfe_pips_at_close     = None
    mae_pips_at_close     = None
    mfe_time_at_close     = None
    mae_time_at_close     = None

    # ── UNTP walk state ───────────────────────────────────────────────────────
    # EC10: stop condition driven by be_triggered (actual state, NOT config).
    untp_stopped = False

    # EC16: frozen peaks captured at the exact candle when UNTP stops.
    # All subsequent snapshot fills and the EC15 fallback use these values
    # instead of the still-accumulating peak_mfe_pips / peak_mae_pips.
    untp_mfe_frozen = None
    untp_mae_frozen = None

    # ── Granular path: [[elapsed_min, mfe_r, mae_r, untp_alive], ...] ─────────
    mfe_path: list = []
    last_path_min  = -PATH_INTERVAL_MIN

    # ── UNTP time-box snapshots (14 checkpoints) ──────────────────────────────
    snaps: list = [
        {"mfe_r": None, "mae_r": None, "outcome": None, "alive": None}
        for _ in CHECKPOINT_KEYS
    ]

    candle_count = 0
    last_close   = None   # EC9: updated every candle for data-ended fallback

    # ── 7. Main candle walk ───────────────────────────────────────────────────
    for _idx, row in df_walk.iterrows():
        candle_time = row["Local time"]
        hi          = row["High"]
        lo          = row["Low"]
        cl          = row["Close"]
        elapsed_min = (candle_time - actual_entry_time).total_seconds() / 60.0

        # EC15: hard cap at 504h (21 days)
        if elapsed_min > UNTP_CAP_MINUTES:
            break

        # ── 7a. MFE / MAE — shared, every candle ─────────────────────────
        if base_trade == "buy":
            candle_mfe = max(hi - actual_entry_price, 0.0) / pip_size
            candle_mae = max(actual_entry_price - lo,  0.0) / pip_size
        else:
            candle_mfe = max(actual_entry_price - lo,  0.0) / pip_size
            candle_mae = max(hi - actual_entry_price,  0.0) / pip_size

        if candle_mfe > peak_mfe_pips:
            peak_mfe_pips = candle_mfe
            if not trade_fully_closed:
                peak_mfe_time = candle_time
        if candle_mae > peak_mae_pips:
            peak_mae_pips = candle_mae
            if not trade_fully_closed:
                peak_mae_time = candle_time

        # ── 7b. R milestones — trade walk only ───────────────────────────
        if not trade_fully_closed:
            current_mfe_r = peak_mfe_pips / sl_distance_pips
            for r_lvl in R_MILESTONES:
                if r_milestone_times[r_lvl] is None and current_mfe_r >= r_lvl:
                    r_milestone_times[r_lvl] = elapsed_min

        # ── 7c. Dip analysis — trade walk only ────────────────────────────
        # EC11: sell dip = price going ABOVE entry (adverse for sell direction)
        if not trade_fully_closed and not dip_ended:
            if base_trade == "buy":
                this_dip           = max(actual_entry_price - lo, 0.0) / pip_size
                favour_this_candle = hi > actual_entry_price
            else:
                this_dip           = max(hi - actual_entry_price, 0.0) / pip_size
                favour_this_candle = lo < actual_entry_price

            if this_dip > peak_dip_pips:
                peak_dip_pips = this_dip
                peak_dip_time = candle_time
            if favour_this_candle:
                dip_ended = True

        # ── 7d. Entry quality — first candles, trade walk only ───────────
        if not trade_fully_closed:
            if candle_count == 0:
                if base_trade == "buy":
                    first_candle_direction = (
                        "favour"  if cl > actual_entry_price else
                        "against" if cl < actual_entry_price else
                        "neutral"
                    )
                else:
                    first_candle_direction = (
                        "favour"  if cl < actual_entry_price else
                        "against" if cl > actual_entry_price else
                        "neutral"
                    )
            if counting_adverse:
                adverse = (
                    cl < actual_entry_price if base_trade == "buy"
                    else cl > actual_entry_price
                )
                if adverse:
                    consecutive_adverse += 1
                else:
                    counting_adverse = False

        # ── 7e. BE check — shared state ───────────────────────────────────
        # EC12: be_trigger_price works for any R/pip value. If TP fires before
        #       be_trigger_price is reached, be_triggered stays False forever.
        if (breakeven_active and be_trigger_price is not None
                and not be_triggered and not trade_fully_closed):
            be_hit = (
                hi >= be_trigger_price if base_trade == "buy"
                else lo <= be_trigger_price
            )
            if be_hit:
                be_triggered    = True
                current_sl      = actual_entry_price  # SL now at entry
                be_trigger_min  = elapsed_min
                mfe_at_be_pips  = peak_mfe_pips
                mfe_at_be_r_val = peak_mfe_pips / sl_distance_pips

        # EC13: mfe_after_be accumulates only while trade is still open
        if be_triggered and not trade_fully_closed:
            additional = peak_mfe_pips - mfe_at_be_pips
            if additional > peak_mfe_after_be:
                peak_mfe_after_be = additional

        # ── 7f. TRADE closing triggers ────────────────────────────────────
        # Priority 1: TP
        if not trade_fully_closed and has_tp:
            tp_hit = (
                hi >= actual_tp if base_trade == "buy"
                else lo <= actual_tp
            )
            if tp_hit:
                trade_fully_closed     = True
                trade_outcome          = "hit_tp"
                exit_price             = actual_tp
                resolution_min         = elapsed_min
                resolution_candle_time = candle_time
                pnl_r_final            = tp_rr_target
                candles_to_resolution  = candle_count + 1
                mfe_pips_at_close      = peak_mfe_pips
                mae_pips_at_close      = peak_mae_pips
                mfe_time_at_close      = peak_mfe_time
                mae_time_at_close      = peak_mae_time
                peak_rr_at_close_val   = tp_rr_target

        # Priority 2: SL or BE-entry retrace (current_sl = entry when BE fired)
        if not trade_fully_closed:
            sl_hit = (
                lo <= current_sl if base_trade == "buy"
                else hi >= current_sl
            )
            if sl_hit:
                trade_fully_closed     = True
                trade_outcome          = "hit_be" if be_triggered else "hit_sl"
                exit_price             = current_sl
                resolution_min         = elapsed_min
                resolution_candle_time = candle_time
                pnl_r_final            = 0.0 if be_triggered else -1.0
                candles_to_resolution  = candle_count + 1
                mfe_pips_at_close      = peak_mfe_pips
                mae_pips_at_close      = peak_mae_pips
                mfe_time_at_close      = peak_mfe_time
                mae_time_at_close      = peak_mae_time
                peak_rr_at_close_val   = peak_mfe_pips / sl_distance_pips

        # ── 7g. UNTP stop check ───────────────────────────────────────────
        # EC10: stop condition is based on be_triggered (actual BE state).
        #       If BE was configured but never fired, entry retrace does NOT
        #       stop the UNTP walk — only the original SL price does.
        #
        # EC16: when UNTP stops, immediately:
        #   a) Capture frozen peaks from this candle's contribution.
        #   b) Backfill ALL not-yet-recorded snapshots with the frozen values
        #      and alive=False. This prevents later candle movement from
        #      inflating mfe_at_Xh_r for checkpoints after the stop.
        #   c) The immediate backfill makes all_snaps_done=True, so the
        #      early-exit at the bottom fires on the next iteration.
        if not untp_stopped:
            if not be_triggered:
                untp_stop = (
                    lo <= original_sl if base_trade == "buy"
                    else hi >= original_sl
                )
            else:
                # BE fired → UNTP stops when price retraces to entry
                untp_stop = (
                    lo <= actual_entry_price if base_trade == "buy"
                    else hi >= actual_entry_price
                )
            if untp_stop:
                untp_stopped    = True
                # EC16a: freeze peaks at this candle (includes 7a contribution above)
                untp_mfe_frozen = peak_mfe_pips
                untp_mae_frozen = peak_mae_pips
                # EC16b: backfill all not-yet-recorded snapshots immediately
                _final_outcome_untp = trade_outcome if trade_fully_closed else "still_open"
                for _j in range(len(CHECKPOINT_KEYS)):
                    if snaps[_j]["alive"] is None:
                        snaps[_j]["mfe_r"]   = untp_mfe_frozen / sl_distance_pips
                        snaps[_j]["mae_r"]   = untp_mae_frozen / sl_distance_pips
                        snaps[_j]["outcome"] = _final_outcome_untp
                        snaps[_j]["alive"]   = False

        # ── 7h. UNTP time-box snapshots ────────────────────────────────────
        # outcome_at_Xh = TRADE outcome; alive_at_Xh = UNTP walk status.
        # EC8: if trade resolves before 30min, the first checkpoint candle
        #      that meets elapsed_min >= cp_min will freeze the snapshot with
        #      the resolved trade_outcome and untp_stopped status.
        # EC16: use frozen peaks when UNTP has stopped so values are not
        #       inflated by candles walked after the UNTP stop. In practice,
        #       after the immediate backfill in 7g, all snaps[i]["alive"] are
        #       already set — this branch only fires for checkpoints reached
        #       BEFORE the UNTP stop (alive=True snapshots).
        for i, cp_min in enumerate(CHECKPOINT_MINUTES):
            if snaps[i]["alive"] is None and elapsed_min >= cp_min:
                _snap_mfe = untp_mfe_frozen if untp_mfe_frozen is not None else peak_mfe_pips
                _snap_mae = untp_mae_frozen if untp_mae_frozen is not None else peak_mae_pips
                snaps[i]["mfe_r"]   = _snap_mfe / sl_distance_pips
                snaps[i]["mae_r"]   = _snap_mae / sl_distance_pips
                snaps[i]["outcome"] = (
                    trade_outcome if trade_fully_closed else "still_open"
                )
                snaps[i]["alive"]   = not untp_stopped

        # ── 7i. Granular path (15-min sampled + forced entries) ────────────
        # EC14: deduplicate when trade close and UNTP stop happen on same candle.
        #       Both events share elapsed_min — only one entry should be written.
        _last_elapsed = mfe_path[-1][0] if mfe_path else None
        _new_elapsed  = round(elapsed_min, 2)
        _is_new_point = _last_elapsed != _new_elapsed

        _is_trade_close = (
            trade_fully_closed
            and candles_to_resolution == candle_count + 1
            and _is_new_point
        )
        _is_untp_stop_event = (
            untp_stopped
            and (not mfe_path or mfe_path[-1][3] != 0)
            and _is_new_point
        )
        _interval_due = elapsed_min >= last_path_min + PATH_INTERVAL_MIN

        if _interval_due or _is_trade_close or _is_untp_stop_event:
            mfe_path.append([
                _new_elapsed,
                round(peak_mfe_pips / sl_distance_pips, 5),
                round(peak_mae_pips / sl_distance_pips, 5),
                0 if untp_stopped else 1,
            ])
            if _interval_due:
                last_path_min += PATH_INTERVAL_MIN

        last_close   = cl
        candle_count += 1

        # ── Early exit: all snapshots recorded AND UNTP done ─────────────
        # EC16c: after immediate backfill in 7g, all_snaps_done becomes True
        # on the very next evaluation here, so the loop exits immediately
        # rather than walking the remaining cap window.
        all_snaps_done = all(s["alive"] is not None for s in snaps)
        if all_snaps_done and (untp_stopped or elapsed_min >= UNTP_CAP_MINUTES):
            break

    # ── 8. Post-walk fallbacks ────────────────────────────────────────────────

    # Freeze at-close peaks for still-open / data-ended trades
    if mfe_pips_at_close is None:
        mfe_pips_at_close = peak_mfe_pips
    if mae_pips_at_close is None:
        mae_pips_at_close = peak_mae_pips
    if mfe_time_at_close is None:
        mfe_time_at_close = peak_mfe_time
    if mae_time_at_close is None:
        mae_time_at_close = peak_mae_time

    # EC9: data ended before resolution — use last seen close price
    if exit_price is None:
        exit_price = last_close

    if candles_to_resolution is None:
        candles_to_resolution = candle_count

    # EC15: fill any snapshots not reached (data ended or cap hit before checkpoint).
    # These are inconclusive — UNTP walk didn't run long enough for this window.
    # EC16: use frozen peaks if UNTP stopped; otherwise use final accumulated peak.
    final_mfe_r = (
        untp_mfe_frozen if untp_mfe_frozen is not None else peak_mfe_pips
    ) / sl_distance_pips
    final_mae_r = (
        untp_mae_frozen if untp_mae_frozen is not None else peak_mae_pips
    ) / sl_distance_pips
    final_outcome = trade_outcome if trade_fully_closed else "still_open"
    for i in range(len(CHECKPOINT_KEYS)):
        if snaps[i]["alive"] is None:
            snaps[i]["mfe_r"]   = final_mfe_r
            snaps[i]["mae_r"]   = final_mae_r
            snaps[i]["outcome"] = final_outcome
            snaps[i]["alive"]   = False  # data ended = inconclusive

    # EC7: single-candle trade — ensure mfe_path has at least one entry
    if not mfe_path and candle_count > 0:
        mfe_path.append([
            0.0,
            round(peak_mfe_pips / sl_distance_pips, 5),
            round(peak_mae_pips / sl_distance_pips, 5),
            0 if untp_stopped else 1,
        ])

    # ── 9. Derive outcome / pnl_r / retracement ──────────────────────────────

    outcome_stored = trade_outcome if trade_fully_closed else (
        "none" if not has_tp else "open"
    )

    # pnl_r: authoritative P&L — single source of truth
    if trade_outcome == "hit_tp":
        pnl_r_out = tp_rr_target
    elif trade_outcome == "hit_sl":
        pnl_r_out = -1.0
    elif trade_outcome == "hit_be":
        pnl_r_out = 0.0
    else:
        pnl_r_out = None

    rr_at_user_tp_out = pnl_r_out   # alias for compatibility

    tp_was_reached = (trade_outcome == "hit_tp")
    time_to_tp_min = resolution_min if tp_was_reached else None

    # Retracement: peak MFE during trade → exit price
    if trade_fully_closed and mfe_pips_at_close > 0:
        if base_trade == "buy":
            peak_price = actual_entry_price + mfe_pips_at_close * pip_size
        else:
            peak_price = actual_entry_price - mfe_pips_at_close * pip_size
        retr_pips = abs(peak_price - exit_price) / pip_size
        retr_r    = retr_pips / sl_distance_pips
    else:
        retr_pips = None
        retr_r    = None

    # Bug 4 Fix: zero out dip if it occurred on the exact candle TP fired.
    # A wide-range candle can have an adverse wick (7c sets dip_occurred) AND
    # reach TP (7f closes trade) in the same iteration because 7c runs before 7f.
    # That would incorrectly classify a "spike to TP on candle 1" trade as
    # "Dip-then-run". Guard: if the peak dip candle is the resolution candle,
    # the dip and TP were simultaneous — no pre-TP dip actually occurred.
    if (trade_fully_closed
            and resolution_candle_time is not None
            and peak_dip_time >= resolution_candle_time):
        peak_dip_pips = 0.0
        peak_dip_time = actual_entry_time

    # Bug 5 Fix: phantom BE trigger when TP and BE fire on the same candle.
    # Step order is 7e (BE check) → 7f (TP check). A large candle can hit
    # be_trigger_price AND actual_tp in the same iteration, leaving
    # be_triggered=True even though TP closed the trade before BE could matter.
    # Override: if outcome is hit_tp and BE trigger time == resolution time,
    # BE was a phantom — clear it so stats correctly reflect a non-BE trade.
    if trade_outcome == "hit_tp" and be_triggered and be_trigger_min == resolution_min:
        be_triggered    = False
        current_sl      = original_sl
        be_trigger_min  = None
        mfe_at_be_pips  = None
        mfe_at_be_r_val = None

    # Dip
    dip_occurred_val = peak_dip_pips > 0.0
    # EC fix: return None when no dip occurred — 0.0 is ambiguous
    # (could mean "dip at exactly entry" vs "no dip at all")
    dip_time_min = (
        (peak_dip_time - actual_entry_time).total_seconds() / 60.0
        if dip_occurred_val else None
    )

    # BE summary
    # EC13: mfe_after_be_r reflects accumulation from BE trigger until trade close
    mfe_after_be_pips_val = peak_mfe_after_be                         if be_triggered else None
    mfe_after_be_r_val    = (peak_mfe_after_be / sl_distance_pips)    if be_triggered else None
    be_sl_price           = actual_entry_price                         if be_triggered else None

    # ── 10. Build result dict ─────────────────────────────────────────────────
    result: dict = {
        "input_type":  input_type,

        "tp_rr_target":   tp_rr_target,
        "tp_pips_target": tp_pips_target,

        "pending_trigger_time":    pending_trigger_time,
        "pending_wait_minutes":    pending_wait_minutes,
        "pending_order_triggered": pending_order_triggered,

        "sl_distance_pips":    sl_distance_pips,
        "mfe_pips":            mfe_pips_at_close,
        "mfe_r":               mfe_pips_at_close / sl_distance_pips,
        "mfe_at_close_pips":   mfe_pips_at_close,
        "mfe_at_close_r":      mfe_pips_at_close / sl_distance_pips,
        "time_to_mfe_minutes": (
            (mfe_time_at_close - actual_entry_time).total_seconds() / 60.0
            if mfe_time_at_close != actual_entry_time else None
        ),
        "mae_pips":            mae_pips_at_close,
        "mae_r":               mae_pips_at_close / sl_distance_pips,
        "time_to_mae_minutes": (
            (mae_time_at_close - actual_entry_time).total_seconds() / 60.0
            if mae_time_at_close != actual_entry_time else None
        ),

        "retracement_from_mfe_pips": retr_pips,
        "retracement_from_mfe_r":    retr_r,

        "exit_price":            exit_price,
        "candles_to_resolution": candles_to_resolution,

        # Bug 1 Fix: use None (not 0.0) when no dip occurred so the template's
        # `if t.dip_pips is not none` check correctly shows "—" instead of "0.0".
        # dip_time_min already guards this correctly; now dip_pips matches.
        "dip_pips":         peak_dip_pips if dip_occurred_val else None,
        "dip_time_minutes": dip_time_min,
        "dip_occurred":     dip_occurred_val,

        "outcome_at_user_tp":         outcome_stored,
        "pnl_r":                      pnl_r_out,
        "rr_at_user_tp":              rr_at_user_tp_out,
        "time_to_resolution_minutes": resolution_min,
        "tp_was_reached":             tp_was_reached,
        "time_to_tp_minutes":         time_to_tp_min,
        "peak_rr_at_close":           peak_rr_at_close_val,

        "breakeven_triggered":             be_triggered,
        "breakeven_sl_price":              be_sl_price,
        "breakeven_trigger_time_minutes":  be_trigger_min,
        "mfe_at_breakeven_pips":           mfe_at_be_pips,
        "mfe_at_breakeven_r":              mfe_at_be_r_val,
        "mfe_after_be_pips":               mfe_after_be_pips_val,
        "mfe_after_be_r":                  mfe_after_be_r_val,

        "time_to_0_5r_minutes": r_milestone_times[0.5],
        "time_to_1r_minutes":   r_milestone_times[1.0],
        "time_to_1_5r_minutes": r_milestone_times[1.5],
        "time_to_2r_minutes":   r_milestone_times[2.0],
        "time_to_3r_minutes":   r_milestone_times[3.0],
        "time_to_4r_minutes":   r_milestone_times[4.0],
        "time_to_5r_minutes":   r_milestone_times[5.0],

        "first_candle_direction":        first_candle_direction,
        "consecutive_adverse_candles":   consecutive_adverse,
        "avg_candle_size_pips_at_entry": avg_candle_size_pips,

        "channel_streak_at_save": _compute_streak(channel_id),

        "entry_day_of_week": entry_day_of_week,
        "entry_hour":        entry_hour,
        "entry_session":     entry_session,

        "mfe_path_json": json.dumps(mfe_path) if mfe_path else None,

        "price_path_captured": True,
    }

    # UNTP time-box snapshots (14 checkpoints × 4 fields = 56 columns)
    for i, key in enumerate(CHECKPOINT_KEYS):
        result[f"mfe_at_{key}_r"]   = snaps[i]["mfe_r"]
        result[f"mae_at_{key}_r"]   = snaps[i]["mae_r"]
        result[f"outcome_at_{key}"] = snaps[i]["outcome"]
        result[f"alive_at_{key}"]   = snaps[i]["alive"]

    logger.info(
        "mfe_calculator: %s %s  outcome=%s  pnl_r=%s  mfe_close=%.2fR  "
        "be_triggered=%s  untp_stopped=%s  untp_frozen=%.2fR  candles=%d",
        sym_key, trade_type, outcome_stored, pnl_r_out,
        mfe_pips_at_close / sl_distance_pips, be_triggered, untp_stopped,
        (untp_mfe_frozen / sl_distance_pips) if untp_mfe_frozen is not None else 0.0,
        candle_count,
    )
    return result