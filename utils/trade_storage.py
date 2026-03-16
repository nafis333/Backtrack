"""
utils/trade_storage.py
----------------------
All database read/write operations for channels and trades.
No Flask imports, no statistics — pure DB access layer.
"""

import csv
import io
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from db import db, Channel, Trade

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# CHANNEL OPERATIONS
# ═══════════════════════════════════════════════════════════════

def get_all_channels(include_archived: bool = False) -> list[Channel]:
    q = Channel.query
    if not include_archived:
        q = q.filter_by(is_archived=False)
    return q.order_by(Channel.name).all()


def get_channel_by_id(channel_id: int) -> Optional[Channel]:
    return Channel.query.get(channel_id)


def create_channel(name: str, description: str = "", color: str = "#4A90D9") -> Channel:
    name = name.strip()
    if not name:
        raise ValueError("Channel name cannot be empty.")
    if Channel.query.filter_by(name=name).first():
        raise ValueError(f"A channel named '{name}' already exists.")
    channel = Channel(name=name, description=description or None, color=color or "#4A90D9")
    db.session.add(channel)
    db.session.commit()
    return channel


def rename_channel(channel_id: int, new_name: str) -> Channel:
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("Channel name cannot be empty.")
    channel = Channel.query.get(channel_id)
    if not channel:
        raise ValueError("Channel not found.")
    existing = Channel.query.filter_by(name=new_name).first()
    if existing and existing.channel_id != channel_id:
        raise ValueError(f"A channel named '{new_name}' already exists.")
    channel.name = new_name
    db.session.commit()
    return channel


def archive_channel(channel_id: int) -> Channel:
    channel = Channel.query.get(channel_id)
    if not channel:
        raise ValueError("Channel not found.")
    # BUG 11 FIX: Guard against no-op to catch double-fire frontend bugs
    if channel.is_archived:
        raise ValueError("Channel is already archived.")
    channel.is_archived = True
    db.session.commit()
    return channel


def unarchive_channel(channel_id: int) -> Channel:
    channel = Channel.query.get(channel_id)
    if not channel:
        raise ValueError("Channel not found.")
    # BUG 11 FIX: Guard against no-op
    if not channel.is_archived:
        raise ValueError("Channel is not archived.")
    channel.is_archived = False
    db.session.commit()
    return channel


def delete_channel(channel_id: int, force: bool = False) -> None:
    channel = Channel.query.get(channel_id)
    if not channel:
        raise ValueError("Channel not found.")
    trade_count = Trade.query.filter_by(channel_id=channel_id).count()
    if trade_count > 0 and not force:
        raise ValueError(
            f"Channel has {trade_count} trade(s). Pass force=True to delete anyway."
        )
    # BUG 1 FIX: Use synchronize_session="fetch" so SQLAlchemy evicts any
    # already-loaded Trade objects from the session before the parent channel
    # is deleted. The old Query.delete() (legacy bulk DELETE) bypassed the
    # ORM unit-of-work entirely, leaving stale in-memory objects and risking
    # FK constraint violations on the subsequent channel row delete.
    db.session.query(Trade).filter_by(channel_id=channel_id).delete(
        synchronize_session="fetch"
    )
    db.session.delete(channel)
    db.session.commit()


# ═══════════════════════════════════════════════════════════════
# CHANNEL METADATA (for cards — no win rate, no PnL)
# ═══════════════════════════════════════════════════════════════

def get_channel_meta(channel_id: int, _trades: list = None) -> dict:
    """
    Single-channel meta — used by channel_detail route.

    Pass _trades (an already-loaded list of ALL trades for this channel) to
    avoid a second DB round-trip when get_channel_detail_context() is used.
    """
    channel = Channel.query.get(channel_id)
    if not channel:
        return {}
    trades = _trades if _trades is not None else Trade.query.filter_by(channel_id=channel_id).all()
    return _build_channel_meta(channel, trades)


def _build_channel_meta(channel: Channel, trades: list[Trade]) -> dict:
    """Internal helper — builds a meta dict from an already-loaded trade list."""
    trade_count = len(trades)
    bad_count   = sum(1 for t in trades if not t.price_path_captured)

    if trade_count == 0:
        return {
            "channel_id":      channel.channel_id,
            "name":            channel.name,
            "description":     channel.description or "",
            "color":           channel.color or "#4A90D9",
            "is_archived":     channel.is_archived,
            "created_at":      channel.created_at,
            "trade_count":     0,
            "date_from":       None,
            "date_to":         None,
            "symbols":         [],
            "has_bad_trades":  False,
            "bad_trade_count": 0,
            "net_r":           0.0,
            "win_rate":        None,
            "evaluated_count": 0,
        }

    entry_times = [t.entry_time for t in trades if t.entry_time]
    symbols     = sorted(set(t.symbol for t in trades))

    # Stats — good trades only (price_path_captured=True)
    # net_r: sum of pnl_r (R2 — pnl_r is authoritative, never derived)
    # win_rate denominator: hit_tp + hit_sl only (same as channel_detail PnL bar)
    good      = [t for t in trades if t.price_path_captured]
    net_r     = sum(t.pnl_r for t in good if t.pnl_r is not None)
    wins      = sum(1 for t in good if t.outcome_at_user_tp == "hit_tp")
    sls       = sum(1 for t in good if t.outcome_at_user_tp == "hit_sl")
    evaluated = wins + sls
    win_rate  = round(wins / evaluated * 100, 1) if evaluated > 0 else None

    return {
        "channel_id":      channel.channel_id,
        "name":            channel.name,
        "description":     channel.description or "",
        "color":           channel.color or "#4A90D9",
        "is_archived":     channel.is_archived,
        "created_at":      channel.created_at,
        "trade_count":     trade_count,
        "date_from":       min(entry_times) if entry_times else None,
        "date_to":         max(entry_times) if entry_times else None,
        "symbols":         symbols,
        "has_bad_trades":  bad_count > 0,
        "bad_trade_count": bad_count,
        "net_r":           round(net_r, 2),
        "win_rate":        win_rate,
        "evaluated_count": evaluated,
    }


def get_all_channel_metas(include_archived: bool = False) -> list[dict]:
    """
    BUG 9 FIX: Was O(N+1) — one Trade query per channel on every /channels
    page load. Now exactly 2 queries total: one for channels, one bulk IN
    query for all their trades, grouped in Python.
    """
    channels = get_all_channels(include_archived=include_archived)
    if not channels:
        return []

    channel_ids = [c.channel_id for c in channels]

    all_trades = Trade.query.filter(Trade.channel_id.in_(channel_ids)).all()

    trades_by_channel: dict[int, list[Trade]] = defaultdict(list)
    for t in all_trades:
        trades_by_channel[t.channel_id].append(t)

    channel_map = {c.channel_id: c for c in channels}

    return [
        _build_channel_meta(channel_map[cid], trades_by_channel[cid])
        for cid in channel_ids
    ]


# ═══════════════════════════════════════════════════════════════
# TRADE OPERATIONS
# ═══════════════════════════════════════════════════════════════

def get_trades_by_channel(
    channel_id: int,
    symbol: str = None,
    trade_type: str = None,
    outcome: str = None,
    date_from: str = None,
    date_to: str = None,
) -> list[Trade]:
    q = Trade.query.filter_by(channel_id=channel_id)

    if symbol and symbol != "all":
        q = q.filter(Trade.symbol == symbol.upper())

    if trade_type and trade_type != "all":
        if trade_type == "buy_side":
            q = q.filter(Trade.trade_type.in_(["buy", "limit_buy", "stop_buy"]))
        elif trade_type == "sell_side":
            q = q.filter(Trade.trade_type.in_(["sell", "limit_sell", "stop_sell"]))
        else:
            q = q.filter(Trade.trade_type == trade_type)

    if outcome and outcome != "all":
        q = q.filter(Trade.outcome_at_user_tp == outcome)

    if date_from:
        try:
            dt = datetime.strptime(date_from, "%Y-%m-%d")
            q = q.filter(Trade.entry_time >= dt)
        except ValueError:
            pass

    if date_to:
        try:
            dt = datetime.strptime(date_to, "%Y-%m-%d")
            q = q.filter(Trade.entry_time < dt + timedelta(days=1))
        except ValueError:
            pass

    return q.order_by(Trade.entry_time.desc()).all()


def get_trade_by_id(trade_id: int) -> Optional[Trade]:
    return Trade.query.get(trade_id)


def delete_trade(trade_id: int) -> int:
    """
    Deletes a trade and returns its channel_id as a plain int.

    Returns int (not Trade): with Flask-SQLAlchemy's default expire_on_commit=True,
    ALL attributes on an ORM object are expired after db.session.commit(). Because
    the trade row is now DELETED, any subsequent attribute access triggers a refresh
    that fails with DetachedInstanceError — the session can't reload a deleted row.
    Capturing channel_id before commit avoids this entirely.
    """
    trade = Trade.query.get(trade_id)
    if not trade:
        raise ValueError("Trade not found.")
    channel_id = trade.channel_id   # capture before delete + commit
    db.session.delete(trade)
    db.session.commit()
    return channel_id


def move_trade(trade_id: int, new_channel_id: int) -> int:
    """
    Moves a trade to a new channel and returns the new channel_id as a plain int.
    Returns int (not Trade) for the same reason as delete_trade — avoids a
    post-commit lazy SELECT on the expired ORM object.
    """
    trade = Trade.query.get(trade_id)
    if not trade:
        raise ValueError("Trade not found.")
    if trade.channel_id == new_channel_id:
        raise ValueError("Trade is already in the selected channel.")
    channel = Channel.query.get(new_channel_id)
    if not channel:
        raise ValueError("Target channel not found.")
    if channel.is_archived:
        raise ValueError("Cannot move trade to an archived channel.")
    trade.channel_id = new_channel_id
    db.session.commit()
    return new_channel_id


def get_incomplete_trades(channel_id: int) -> list[Trade]:
    """Returns trades where price_path_captured=False."""
    return Trade.query.filter_by(
        channel_id=channel_id,
        price_path_captured=False
    ).all()


# ═══════════════════════════════════════════════════════════════
# CSV EXPORT
# ═══════════════════════════════════════════════════════════════

_CSV_COLUMNS = [
    "trade_id", "symbol", "trade_type", "entry_time", "entry_price",
    "stoploss_price", "takeprofit_price", "limit_price",
    "breakeven_active", "breakeven_type", "breakeven_value",
    "sl_distance_pips", "tp_rr_target", "tp_pips_target",
    "outcome_at_user_tp", "pnl_r", "exit_price",
    "mfe_r", "mae_r", "mfe_at_close_r",
    "time_to_resolution_minutes", "candles_to_resolution",
    "dip_pips", "dip_occurred",
    "breakeven_triggered", "mfe_at_breakeven_r", "mfe_after_be_r",
    "entry_session", "entry_day_of_week", "entry_hour",
    "price_path_captured", "notes", "saved_at",
    # UNTP snapshots — 14 checkpoints × 4 fields = 56 columns
    "mfe_at_30min_r",  "mae_at_30min_r",  "outcome_at_30min",  "alive_at_30min",
    "mfe_at_1h_r",     "mae_at_1h_r",     "outcome_at_1h",     "alive_at_1h",
    "mfe_at_2h_r",     "mae_at_2h_r",     "outcome_at_2h",     "alive_at_2h",
    "mfe_at_4h_r",     "mae_at_4h_r",     "outcome_at_4h",     "alive_at_4h",
    "mfe_at_8h_r",     "mae_at_8h_r",     "outcome_at_8h",     "alive_at_8h",
    "mfe_at_12h_r",    "mae_at_12h_r",    "outcome_at_12h",    "alive_at_12h",
    "mfe_at_24h_r",    "mae_at_24h_r",    "outcome_at_24h",    "alive_at_24h",
    "mfe_at_48h_r",    "mae_at_48h_r",    "outcome_at_48h",    "alive_at_48h",
    "mfe_at_72h_r",    "mae_at_72h_r",    "outcome_at_72h",    "alive_at_72h",
    "mfe_at_120h_r",   "mae_at_120h_r",   "outcome_at_120h",   "alive_at_120h",
    "mfe_at_168h_r",   "mae_at_168h_r",   "outcome_at_168h",   "alive_at_168h",
    "mfe_at_240h_r",   "mae_at_240h_r",   "outcome_at_240h",   "alive_at_240h",
    "mfe_at_336h_r",   "mae_at_336h_r",   "outcome_at_336h",   "alive_at_336h",
    "mfe_at_504h_r",   "mae_at_504h_r",   "outcome_at_504h",   "alive_at_504h",
    "mfe_path_json",
]


def export_trades_csv(
    channel_id: int,
    symbol: str = None,
    trade_type: str = None,
    outcome: str = None,
    date_from: str = None,
    date_to: str = None,
) -> str:
    trades = get_trades_by_channel(
        channel_id, symbol=symbol, trade_type=trade_type,
        outcome=outcome, date_from=date_from, date_to=date_to,
    )
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for t in trades:
        d = t.to_dict()
        writer.writerow({col: d.get(col, "") for col in _CSV_COLUMNS})
    return output.getvalue()


# ═══════════════════════════════════════════════════════════════
# FILTER OPTIONS (for dropdowns in channel detail)
# ═══════════════════════════════════════════════════════════════

def get_channel_filter_options(channel_id: int, _trades: list = None) -> dict:
    """
    Returns the unique values for each filter dropdown in channel_detail.

    Pass _trades (pre-loaded) to avoid a redundant DB round-trip when called
    alongside get_channel_meta() in the same request.
    """
    trades      = _trades if _trades is not None else Trade.query.filter_by(channel_id=channel_id).all()
    symbols     = sorted(set(t.symbol             for t in trades if t.symbol))
    outcomes    = sorted(set(t.outcome_at_user_tp for t in trades if t.outcome_at_user_tp))
    trade_types = sorted(set(t.trade_type         for t in trades if t.trade_type))
    return {"symbols": symbols, "outcomes": outcomes, "trade_types": trade_types}


def get_channel_detail_context(channel_id: int) -> tuple[dict, dict]:
    """
    Load ALL (unfiltered) trades for a channel once, then derive both
    channel meta and filter options from that single list.

    Returns (meta_dict, filter_options_dict).

    Reduces the channel_detail page load from 6 DB queries to 4:
      Before: get_channel_by_id + get_trades_by_channel (filtered) +
              get_channel_filter_options (all) + get_channel_meta (channel + all)
              = 2 Channel queries + 3 Trade queries
      After:  get_channel_by_id + get_trades_by_channel (filtered) +
              THIS (1 Trade query shared by both meta and filter_options) +
              get_all_channels
              = 2 Channel queries + 2 Trade queries
    """
    all_trades     = Trade.query.filter_by(channel_id=channel_id).all()
    meta           = get_channel_meta(channel_id, _trades=all_trades)
    filter_options = get_channel_filter_options(channel_id, _trades=all_trades)
    return meta, filter_options