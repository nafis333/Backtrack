"""
save_routes.py
--------------
Flask Blueprint:
  POST /save_trade          — save a monitored trade to a channel
  GET  /channels/list_json  — channel list for the modal dropdown
"""

import logging
import pandas as pd
from flask import Blueprint, request, jsonify
from datetime import datetime

from db import db, Channel, Trade
from utils.mfe_calculator import calculate_mfe

save_bp = Blueprint("save_bp", __name__)
logger  = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _get_or_create_channel(channel_id: str, new_channel_name: str,
                            new_channel_description: str = "",
                            new_channel_color: str = "#4A90D9") -> Channel:
    if channel_id == "new":
        name = (new_channel_name or "").strip()
        if not name:
            raise ValueError("Channel name cannot be empty.")
        if Channel.query.filter_by(name=name).first():
            raise ValueError(f"A channel named '{name}' already exists.")
        # BUG 6 FIX: Old code constructed Channel(name=name) only, silently
        # dropping description and color. If Channel.color has no model-level
        # default this stored NULL, breaking any template rendering the color
        # dot. Now passes both fields, matching create_channel() behaviour.
        channel = Channel(
            name=name,
            description=new_channel_description.strip() or None,
            color=new_channel_color.strip() or "#4A90D9",
        )
        db.session.add(channel)
        db.session.flush()
        return channel
    try:
        cid = int(channel_id)
    except (TypeError, ValueError):
        raise ValueError("Invalid channel selection.")
    channel = Channel.query.get(cid)
    if not channel:
        raise ValueError("Selected channel does not exist.")
    if channel.is_archived:
        raise ValueError("Cannot save to an archived channel.")
    return channel


def _f(val):
    """Parse string to float or None."""
    if val is None or str(val).strip() == "":
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _parse_form(form) -> dict:
    for field in ["symbol", "trade_type", "entry_time", "entry_price", "stoploss_price"]:
        if not form.get(field, "").strip():
            raise ValueError(f"Missing required field: {field}")
    try:
        entry_time = datetime.strptime(form["entry_time"].strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        raise ValueError("Invalid entry_time (expected YYYY-MM-DD HH:MM).")
    try:
        entry_price    = float(form["entry_price"])
        stoploss_price = float(form["stoploss_price"])
    except ValueError:
        raise ValueError("entry_price and stoploss_price must be numbers.")

    be_raw = form.get("breakeven_active", "false").strip().lower()
    return {
        "symbol":           form["symbol"].strip().upper(),
        "trade_type":       form["trade_type"].strip().lower(),
        "entry_time":       entry_time,
        "entry_price":      entry_price,
        "stoploss_price":   stoploss_price,
        "takeprofit_price": _f(form.get("takeprofit_price")),
        "limit_price":      _f(form.get("limit_price")),
        "breakeven_active": be_raw in {"true", "1", "yes"},
        "breakeven_type":   form.get("breakeven_type", "").strip().lower() or None,
        "breakeven_value":  _f(form.get("breakeven_value")),
        "input_type":       form.get("input_type", "").strip().lower() or None,
        "notes":            (form.get("notes", "") or "").strip()[:1000],
    }


# --------------------------------------------------------------------------- #
# POST /save_trade
# --------------------------------------------------------------------------- #

@save_bp.route("/save_trade", methods=["POST"])
def save_trade():
    try:
        parsed  = _parse_form(request.form)
        channel = _get_or_create_channel(
            request.form.get("channel_id", "").strip(),
            request.form.get("new_channel_name", "").strip(),
            request.form.get("new_channel_description", "").strip(),  
            request.form.get("new_channel_color", "#4A90D9").strip(), 
        )

        mfe = calculate_mfe(
            entry_time        = pd.Timestamp(parsed["entry_time"]),
            entry_price       = parsed["entry_price"],
            stoploss_price    = parsed["stoploss_price"],
            takeprofit_price  = parsed["takeprofit_price"],
            trade_type        = parsed["trade_type"],
            symbol            = parsed["symbol"],
            limit_price       = parsed["limit_price"],
            breakeven_active  = parsed["breakeven_active"],
            breakeven_type    = parsed["breakeven_type"],
            breakeven_value   = parsed["breakeven_value"],
            input_type        = parsed["input_type"],
            channel_id        = channel.channel_id,
        )

        trade = Trade(
            channel_id       = channel.channel_id,
            symbol           = parsed["symbol"],
            trade_type       = parsed["trade_type"],
            entry_time       = parsed["entry_time"],
            entry_price      = parsed["entry_price"],
            stoploss_price   = parsed["stoploss_price"],
            takeprofit_price = parsed["takeprofit_price"],
            limit_price      = parsed["limit_price"],
            breakeven_active = parsed["breakeven_active"],
            breakeven_type   = parsed["breakeven_type"],
            breakeven_value  = parsed["breakeven_value"],
            notes            = parsed["notes"],

            # ── auto-computed from mfe_calculator ────────────────────────
            input_type                       = mfe["input_type"],
            tp_rr_target                     = mfe["tp_rr_target"],
            tp_pips_target                   = mfe["tp_pips_target"],
            pending_trigger_time             = mfe["pending_trigger_time"],
            pending_wait_minutes             = mfe["pending_wait_minutes"],
            pending_order_triggered          = mfe["pending_order_triggered"],
            sl_distance_pips                 = mfe["sl_distance_pips"],
            mfe_pips                         = mfe["mfe_pips"],
            mfe_r                            = mfe["mfe_r"],
            mfe_at_close_pips                = mfe["mfe_at_close_pips"],
            mfe_at_close_r                   = mfe["mfe_at_close_r"],
            time_to_mfe_minutes              = mfe["time_to_mfe_minutes"],
            mae_pips                         = mfe["mae_pips"],
            mae_r                            = mfe["mae_r"],
            time_to_mae_minutes              = mfe["time_to_mae_minutes"],
            retracement_from_mfe_pips        = mfe["retracement_from_mfe_pips"],
            retracement_from_mfe_r           = mfe["retracement_from_mfe_r"],
            exit_price                       = mfe["exit_price"],
            candles_to_resolution            = mfe["candles_to_resolution"],
            dip_pips                         = mfe["dip_pips"],
            dip_time_minutes                 = mfe["dip_time_minutes"],
            dip_occurred                     = mfe["dip_occurred"],
            outcome_at_user_tp               = mfe["outcome_at_user_tp"],
            pnl_r                            = mfe["pnl_r"],
            rr_at_user_tp                    = mfe["rr_at_user_tp"],
            time_to_resolution_minutes       = mfe["time_to_resolution_minutes"],
            tp_was_reached                   = mfe["tp_was_reached"],
            time_to_tp_minutes               = mfe["time_to_tp_minutes"],
            peak_rr_at_close                 = mfe["peak_rr_at_close"],
            breakeven_triggered              = mfe["breakeven_triggered"],
            breakeven_sl_price               = mfe["breakeven_sl_price"],
            breakeven_trigger_time_minutes   = mfe["breakeven_trigger_time_minutes"],
            mfe_at_breakeven_pips            = mfe["mfe_at_breakeven_pips"],
            mfe_at_breakeven_r               = mfe["mfe_at_breakeven_r"],
            mfe_after_be_pips                = mfe["mfe_after_be_pips"],
            mfe_after_be_r                   = mfe["mfe_after_be_r"],
            time_to_0_5r_minutes             = mfe["time_to_0_5r_minutes"],
            time_to_1r_minutes               = mfe["time_to_1r_minutes"],
            time_to_1_5r_minutes             = mfe["time_to_1_5r_minutes"],
            time_to_2r_minutes               = mfe["time_to_2r_minutes"],
            time_to_3r_minutes               = mfe["time_to_3r_minutes"],
            time_to_4r_minutes               = mfe["time_to_4r_minutes"],
            time_to_5r_minutes               = mfe["time_to_5r_minutes"],

            # ── UNTP time-box snapshots — 14 checkpoints ─────────────────
            mfe_at_30min_r  = mfe["mfe_at_30min_r"],  mae_at_30min_r  = mfe["mae_at_30min_r"],  outcome_at_30min = mfe["outcome_at_30min"],  alive_at_30min = mfe["alive_at_30min"],
            mfe_at_1h_r     = mfe["mfe_at_1h_r"],     mae_at_1h_r     = mfe["mae_at_1h_r"],     outcome_at_1h    = mfe["outcome_at_1h"],     alive_at_1h    = mfe["alive_at_1h"],
            mfe_at_2h_r     = mfe["mfe_at_2h_r"],     mae_at_2h_r     = mfe["mae_at_2h_r"],     outcome_at_2h    = mfe["outcome_at_2h"],     alive_at_2h    = mfe["alive_at_2h"],
            mfe_at_4h_r     = mfe["mfe_at_4h_r"],     mae_at_4h_r     = mfe["mae_at_4h_r"],     outcome_at_4h    = mfe["outcome_at_4h"],     alive_at_4h    = mfe["alive_at_4h"],
            mfe_at_8h_r     = mfe["mfe_at_8h_r"],     mae_at_8h_r     = mfe["mae_at_8h_r"],     outcome_at_8h    = mfe["outcome_at_8h"],     alive_at_8h    = mfe["alive_at_8h"],
            mfe_at_12h_r    = mfe["mfe_at_12h_r"],    mae_at_12h_r    = mfe["mae_at_12h_r"],    outcome_at_12h   = mfe["outcome_at_12h"],    alive_at_12h   = mfe["alive_at_12h"],
            mfe_at_24h_r    = mfe["mfe_at_24h_r"],    mae_at_24h_r    = mfe["mae_at_24h_r"],    outcome_at_24h   = mfe["outcome_at_24h"],    alive_at_24h   = mfe["alive_at_24h"],
            mfe_at_48h_r    = mfe["mfe_at_48h_r"],    mae_at_48h_r    = mfe["mae_at_48h_r"],    outcome_at_48h   = mfe["outcome_at_48h"],    alive_at_48h   = mfe["alive_at_48h"],
            mfe_at_72h_r    = mfe["mfe_at_72h_r"],    mae_at_72h_r    = mfe["mae_at_72h_r"],    outcome_at_72h   = mfe["outcome_at_72h"],    alive_at_72h   = mfe["alive_at_72h"],
            mfe_at_120h_r   = mfe["mfe_at_120h_r"],   mae_at_120h_r   = mfe["mae_at_120h_r"],   outcome_at_120h  = mfe["outcome_at_120h"],   alive_at_120h  = mfe["alive_at_120h"],
            mfe_at_168h_r   = mfe["mfe_at_168h_r"],   mae_at_168h_r   = mfe["mae_at_168h_r"],   outcome_at_168h  = mfe["outcome_at_168h"],   alive_at_168h  = mfe["alive_at_168h"],
            mfe_at_240h_r   = mfe["mfe_at_240h_r"],   mae_at_240h_r   = mfe["mae_at_240h_r"],   outcome_at_240h  = mfe["outcome_at_240h"],   alive_at_240h  = mfe["alive_at_240h"],
            mfe_at_336h_r   = mfe["mfe_at_336h_r"],   mae_at_336h_r   = mfe["mae_at_336h_r"],   outcome_at_336h  = mfe["outcome_at_336h"],   alive_at_336h  = mfe["alive_at_336h"],
            mfe_at_504h_r   = mfe["mfe_at_504h_r"],   mae_at_504h_r   = mfe["mae_at_504h_r"],   outcome_at_504h  = mfe["outcome_at_504h"],   alive_at_504h  = mfe["alive_at_504h"],

            # ── entry quality ─────────────────────────────────────────────
            first_candle_direction        = mfe["first_candle_direction"],
            consecutive_adverse_candles   = mfe["consecutive_adverse_candles"],
            avg_candle_size_pips_at_entry = mfe["avg_candle_size_pips_at_entry"],
            channel_streak_at_save        = mfe["channel_streak_at_save"],

            # ── session ───────────────────────────────────────────────────
            entry_day_of_week   = mfe["entry_day_of_week"],
            entry_hour          = mfe["entry_hour"],
            entry_session       = mfe["entry_session"],
            price_path_captured = mfe["price_path_captured"],
            mfe_path_json       = mfe["mfe_path_json"],
        )

        db.session.add(trade)
        db.session.commit()
        logger.info(
            "Trade %s → channel '%s' | outcome=%s  pnl_r=%s  path=%s",
            trade.trade_id, channel.name,
            trade.outcome_at_user_tp, trade.pnl_r, trade.price_path_captured,
        )

        return jsonify({
            "success":             True,
            "trade_id":            trade.trade_id,
            "channel_name":        channel.name,
            "price_path_captured": trade.price_path_captured,
        })

    except ValueError as e:
        db.session.rollback()
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        logger.exception(f"Unexpected error in save_trade: {e}")
        return jsonify({"success": False, "error": "An unexpected error occurred."}), 500


# --------------------------------------------------------------------------- #
# GET /channels/list_json
# --------------------------------------------------------------------------- #

@save_bp.route("/channels/list_json", methods=["GET"])
def list_channels_json():
    channels = Channel.query.filter_by(is_archived=False).order_by(Channel.name).all()
    return jsonify([
        {"channel_id": c.channel_id, "name": c.name, "color": c.color}
        for c in channels
    ])