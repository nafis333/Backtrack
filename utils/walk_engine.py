"""
utils/walk_engine.py
--------------------
Query-time parquet re-walk engine for statistics modules.

Used by:
  POST /statistics/overview  (fixed_untp, untp_overview modes — Phase 6+)
  POST /statistics/sweep     (M3 RR Sweep)
  POST /statistics/becompare (M4 BE Comparison)

NOT used at save time — mfe_calculator.py handles save-time walks.
Never writes to DB. Never reads from DB. No Flask imports.

Public API
----------
walk_trade_untp(trade, data_frames, max_minutes, be_active, be_trigger_r) -> dict

  Walks parquet candle-by-candle from trade entry. Returns peak MFE/MAE,
  stop reason, and full path. Uses already-loaded data_frames (zero disk I/O).

  BE logic is entirely user-defined. The trade's saved breakeven config
  (breakeven_active, breakeven_type, breakeven_value) is NEVER read.
  be_trigger_r is a user-supplied R level per request. (DECISION-22, R10)

Raises WalkDataError when:
  - Symbol not in data_frames
  - No candle data exists after entry_time

stop_reason values:
  'sl'         original SL hit
  'be'         BE triggered at be_trigger_r, then price retraced to entry
  'time_limit' max_minutes reached before natural stop
  'open'       parquet data exhausted before any stop (trade still running)
"""

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

UNTP_CAP_MINUTES = 30240  # 504h hard cap — always enforced

try:
    from utils.pip_utils import get_pip_size as _get_pip_size
except (ImportError, AttributeError):
    logger.warning(
        "walk_engine: could not import get_pip_size from utils.pip_utils — "
        "using local fallback. Keep in sync with pip_utils.py."
    )
    def _get_pip_size(symbol: str) -> float:  # type: ignore[misc]
        sym = symbol.upper()
        if sym == "XAUUSD":             return 0.1
        if sym == "XAGUSD":             return 0.01
        if sym in {"NAS100", "US30"}:   return 1.0
        if sym in {"USOIL", "UKOIL"}:   return 0.1
        return 0.01 if "JPY" in sym else 0.0001


class WalkDataError(Exception):
    """Raised when parquet data is unavailable for a trade.

    Callers must catch this and exclude the trade from results,
    incrementing excluded_count with reason 'no_price_data'.
    """


def walk_trade_untp(
    trade: dict,
    data_frames: dict,
    max_minutes: int,
    be_active: bool,
    be_trigger_r: Optional[float],
) -> dict:
    """
    Re-walk a trade from entry using parquet price data.

    Parameters
    ----------
    trade         : trade dict from Trade.to_dict()
    data_frames   : already-loaded parquet DataFrames from data_loader
    max_minutes   : walk cap in minutes (use UNTP_CAP_MINUTES for 'no limit')
    be_active     : True = apply BE at be_trigger_r; False = walk to SL only
    be_trigger_r  : R level at which BE activates (required when be_active=True)

    Returns
    -------
    dict with keys:
      peak_mfe_r     float    highest MFE in R reached during walk
      peak_mae_r     float    highest MAE in R reached during walk
      stop_reason    str      'sl' | 'be' | 'time_limit' | 'open'
      stopped_at_min int|None elapsed minutes at stop (None if open)
      path           list     [[elapsed_min, mfe_r, mae_r], ...] every candle

    Raises
    ------
    WalkDataError  if symbol not in data_frames or no candle data after entry
    """

    # ── Extract fields from trade dict ────────────────────────────────────────
    sym_key        = (trade.get("symbol") or "").upper()
    trade_type     = trade.get("trade_type") or ""
    entry_time     = trade.get("entry_time")
    entry_price    = trade.get("entry_price")
    stoploss_price = trade.get("stoploss_price")

    if not sym_key:
        raise WalkDataError("trade has no symbol")
    if entry_price is None or stoploss_price is None:
        raise WalkDataError(f"trade missing entry_price or stoploss_price [{sym_key}]")

    entry_price = float(entry_price)
    original_sl = float(stoploss_price)
    base_trade  = "buy" if "buy" in trade_type else "sell"

    # ── Normalise entry_time to datetime ─────────────────────────────────────
    if isinstance(entry_time, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                entry_time = datetime.strptime(entry_time, fmt)
                break
            except ValueError:
                continue
        else:
            raise WalkDataError(f"cannot parse entry_time: {entry_time}")
    if entry_time is None:
        raise WalkDataError("trade has no entry_time")

    # ── Fetch parquet data ────────────────────────────────────────────────────
    if sym_key not in data_frames:
        raise WalkDataError(f"no parquet data loaded for symbol: {sym_key}")

    df      = data_frames[sym_key]
    df_walk = (
        df[df["Local time"] > entry_time]
        .sort_values("Local time")
        .reset_index(drop=True)
    )

    if df_walk.empty:
        raise WalkDataError(
            f"no candle data after entry_time {entry_time} for {sym_key}"
        )

    # ── Pre-compute invariants ────────────────────────────────────────────────
    pip_size         = _get_pip_size(sym_key)
    sl_distance_pips = abs(entry_price - original_sl) / pip_size

    if sl_distance_pips == 0:
        raise WalkDataError(
            f"SL distance is zero for {sym_key} at {entry_time}"
        )

    # Enforce hard cap
    effective_cap = min(int(max_minutes), UNTP_CAP_MINUTES)

    # ── BE trigger price (user-defined, NEVER from saved trade config) ────────
    # R10: be_trigger_r is always user-supplied per request.
    be_trigger_price: Optional[float] = None
    if be_active and be_trigger_r is not None and be_trigger_r > 0:
        sl_distance_price = sl_distance_pips * pip_size
        if base_trade == "buy":
            be_trigger_price = entry_price + sl_distance_price * be_trigger_r
        else:
            be_trigger_price = entry_price - sl_distance_price * be_trigger_r

    # ── Walk state ────────────────────────────────────────────────────────────
    peak_mfe_pips: float  = 0.0
    peak_mae_pips: float  = 0.0
    be_triggered: bool    = False
    current_sl: float     = original_sl
    path: list            = []
    stop_reason: Optional[str]    = None
    stopped_at_min: Optional[int] = None

    # ── Main candle walk ──────────────────────────────────────────────────────
    for _, row in df_walk.iterrows():
        candle_time = row["Local time"]
        hi          = row["High"]
        lo          = row["Low"]
        elapsed_min = (candle_time - entry_time).total_seconds() / 60.0

        # Hard cap check
        if elapsed_min > effective_cap:
            stop_reason    = "time_limit"
            stopped_at_min = effective_cap
            break

        # ── MFE / MAE accumulation ────────────────────────────────────────
        if base_trade == "buy":
            candle_mfe = max(hi - entry_price, 0.0) / pip_size
            candle_mae = max(entry_price - lo,  0.0) / pip_size
        else:
            candle_mfe = max(entry_price - lo,  0.0) / pip_size
            candle_mae = max(hi - entry_price,  0.0) / pip_size

        if candle_mfe > peak_mfe_pips:
            peak_mfe_pips = candle_mfe
        if candle_mae > peak_mae_pips:
            peak_mae_pips = candle_mae

        # ── BE trigger check (only when be_active=True) ───────────────────
        if be_active and be_trigger_price is not None and not be_triggered:
            be_hit = (
                hi >= be_trigger_price if base_trade == "buy"
                else lo <= be_trigger_price
            )
            if be_hit:
                be_triggered = True
                current_sl   = entry_price   # SL moves to entry

        # ── Natural stop check ────────────────────────────────────────────
        # current_sl = entry_price after BE fires, original_sl before
        stopped = (
            lo <= current_sl if base_trade == "buy"
            else hi >= current_sl
        )

        if stopped:
            stop_reason    = "be" if be_triggered else "sl"
            stopped_at_min = int(elapsed_min)
            # Record final point before breaking
            path.append([
                int(elapsed_min),
                round(peak_mfe_pips / sl_distance_pips, 4),
                round(peak_mae_pips / sl_distance_pips, 4),
            ])
            break

        # ── Record path point every candle ───────────────────────────────
        path.append([
            int(elapsed_min),
            round(peak_mfe_pips / sl_distance_pips, 4),
            round(peak_mae_pips / sl_distance_pips, 4),
        ])

    else:
        # Loop exhausted all parquet data without hitting any stop
        stop_reason    = "open"
        stopped_at_min = None

    return {
        "peak_mfe_r":     round(peak_mfe_pips / sl_distance_pips, 4),
        "peak_mae_r":     round(peak_mae_pips / sl_distance_pips, 4),
        "stop_reason":    stop_reason,
        "stopped_at_min": stopped_at_min,
        "path":           path,
    }