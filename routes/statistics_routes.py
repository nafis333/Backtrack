"""
routes/statistics_routes.py
----------------------------
Statistics hub routes.

GET  /statistics          — render hub page
POST /statistics/overview — JSON API for all 4 modes
GET  /statistics/symbols  — symbols for filter dropdown

MODE DISPATCH:
  original_tp  → compute_overview()   result_type='overview'
  fixed_tp     → compute_overview()   result_type='overview'
  fixed_untp   → compute_untp_stats() result_type='untp_stats'
  untp_overview→ compute_untp_stats() result_type='untp_stats'

SERVER ENFORCEMENT:
  original_tp / fixed_tp  → time_limit_hours forced to None regardless of UI input.
  fixed_untp / untp_overview → time_limit_hours required; returns 400 if missing.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from flask import Blueprint, render_template, request, jsonify

from db import db, Trade
from utils.trade_storage import get_all_channels
from utils.trade_statistics import (
    compute_overview,
    compute_untp_stats,
    compute_fixed_untp_overview,
    compute_hit_rate,
    compute_pnl_report,
    TIME_LIMIT_LABELS,
    VALID_TP_MODES,
    VALID_UNITS,
)

logger = logging.getLogger(__name__)

stats_bp = Blueprint('stats', __name__)


# ═══════════════════════════════════════════════════════════════
# PAGE ROUTE
# ═══════════════════════════════════════════════════════════════

@stats_bp.route('/statistics')
def statistics_hub():
    channels = get_all_channels(include_archived=False)

    symbol_rows = (
        db.session.query(Trade.symbol)
        .distinct()
        .order_by(Trade.symbol)
        .all()
    )
    symbols = [row[0] for row in symbol_rows]

    # UNTP modes require a real checkpoint — exclude the "No limit" entry
    time_limit_options = [
        {'value': k, 'label': v}
        for k, v in TIME_LIMIT_LABELS.items()
        if k is not None
    ]

    return render_template(
        'statistics.html',
        channels=channels,
        symbols=symbols,
        time_limit_options=time_limit_options,
    )


# ═══════════════════════════════════════════════════════════════
# API — ALL MODES
# ═══════════════════════════════════════════════════════════════

@stats_bp.route('/statistics/overview', methods=['POST'])
def statistics_overview():
    """
    Request body:
      {
        channel_ids:       [int, ...]
        date_from:         "YYYY-MM-DD"   optional
        date_to:           "YYYY-MM-DD"   optional
        symbol:            "EURUSD"       optional, "all" = all
        trade_type:        "all" | "buy" | "sell" | "limit_buy" | ...
        tp_mode:           "original_tp" | "fixed_tp" | "fixed_untp" | "untp_overview"
        tp_value:          float          required for fixed_tp / fixed_untp
        unit:              "R" | "pips"   for fixed_tp / fixed_untp
        time_limit_hours:  float          required for fixed_untp / untp_overview
      }

    Note: BE toggle is client-side only — three groups pre-computed in one response.
    """
    data = request.get_json(force=True) or {}

    # ── Validate mode ────────────────────────────────────────
    tp_mode = data.get('tp_mode', 'original_tp')
    if tp_mode not in VALID_TP_MODES:
        return jsonify({'error': f"Invalid tp_mode: {tp_mode}"}), 400

    # ── Validate unit ────────────────────────────────────────
    unit = data.get('unit', 'R')
    if unit not in VALID_UNITS:
        return jsonify({'error': f"Invalid unit: {unit}. Must be 'R' or 'pips'"}), 400

    # ── TP value (required for fixed_tp / fixed_untp) ────────
    tp_value: Optional[float] = _parse_float(data.get('tp_value'))
    if tp_mode in ('fixed_tp', 'fixed_untp') and (tp_value is None or tp_value <= 0):
        return jsonify({'error': 'tp_value must be a positive number for fixed_tp / fixed_untp'}), 400

    # ── Time limit — server enforcement ─────────────────────
    time_limit_hours: Optional[float] = _parse_float(data.get('time_limit_hours'))

    if tp_mode in ('original_tp', 'fixed_tp'):
        # Time limit has no meaning — force None
        if time_limit_hours is not None:
            logger.debug("time_limit_hours ignored for tp_mode=%s", tp_mode)
        time_limit_hours = None

    if tp_mode in ('fixed_untp', 'untp_overview'):
        if time_limit_hours is None or time_limit_hours <= 0:
            return jsonify({
                'error': f"time_limit_hours is required for tp_mode={tp_mode}"
            }), 400

    # ── Load trades ──────────────────────────────────────────
    try:
        trades = _load_trades(data)
    except Exception as exc:
        logger.exception("Error loading trades for statistics")
        return jsonify({'error': str(exc)}), 500

    trade_dicts = [t.to_dict() for t in trades]

    # ── Dispatch ─────────────────────────────────────────────
    try:
        if tp_mode == 'untp_overview':
            result = compute_untp_stats(
                trade_dicts,
                time_limit_hours=time_limit_hours,
                tp_mode='untp_overview',
                tp_value=None,
                unit=unit,
            )
        elif tp_mode == 'fixed_untp':
            result = compute_fixed_untp_overview(
                trade_dicts,
                tp_value=tp_value,
                time_limit_hours=time_limit_hours,
                unit=unit,
            )
        else:
            result = compute_overview(trade_dicts, tp_mode, tp_value, None, unit)
    except Exception as exc:
        logger.exception("Error computing statistics")
        return jsonify({'error': str(exc)}), 500

    return jsonify(result)


@stats_bp.route('/statistics/hitrate', methods=['POST'])
def statistics_hitrate():
    """
    POST /statistics/hitrate
    Same request body as /statistics/overview.
    Returns result_type='hitrate' with per-dimension breakdown rows.
    """
    data = request.get_json(force=True) or {}

    tp_mode = data.get('tp_mode', 'original_tp')
    if tp_mode not in VALID_TP_MODES:
        return jsonify({'error': f"Invalid tp_mode: {tp_mode}"}), 400

    unit = data.get('unit', 'R')
    if unit not in VALID_UNITS:
        return jsonify({'error': f"Invalid unit: {unit}"}), 400

    tp_value: Optional[float] = _parse_float(data.get('tp_value'))
    if tp_mode in ('fixed_tp', 'fixed_untp') and (tp_value is None or tp_value <= 0):
        return jsonify({'error': 'tp_value required for fixed_tp / fixed_untp'}), 400

    time_limit_hours: Optional[float] = _parse_float(data.get('time_limit_hours'))
    if tp_mode in ('original_tp', 'fixed_tp'):
        time_limit_hours = None
    if tp_mode in ('fixed_untp', 'untp_overview'):
        if time_limit_hours is None or time_limit_hours <= 0:
            return jsonify({'error': f"time_limit_hours required for {tp_mode}"}), 400

    try:
        trades = _load_trades(data)
    except Exception as exc:
        logger.exception("Error loading trades for hit rate")
        return jsonify({'error': str(exc)}), 500

    try:
        result = compute_hit_rate(
            [t.to_dict() for t in trades],
            tp_mode=tp_mode,
            tp_value=tp_value,
            time_limit_hours=time_limit_hours,
            unit=unit,
        )
    except Exception as exc:
        logger.exception("Error computing hit rate")
        return jsonify({'error': str(exc)}), 500

    return jsonify(result)


@stats_bp.route('/statistics/pnl', methods=['POST'])
def statistics_pnl():
    """
    POST /statistics/pnl
    Same filter fields as /statistics/overview.
    Ignores tp_mode, tp_value, unit, time_limit_hours — uses pnl_r directly (R2).
    Returns result_type='pnl_report'.
    """
    data = request.get_json(force=True) or {}

    try:
        trades = _load_trades(data)
    except Exception as exc:
        logger.exception("Error loading trades for PnL report")
        return jsonify({'error': str(exc)}), 500

    try:
        result = compute_pnl_report([t.to_dict() for t in trades])
    except Exception as exc:
        logger.exception("Error computing PnL report")
        return jsonify({'error': str(exc)}), 500

    return jsonify(result)

# ═══════════════════════════════════════════════════════════════
# API — SYMBOL FILTER
# ═══════════════════════════════════════════════════════════════

@stats_bp.route('/statistics/symbols', methods=['POST'])
def statistics_symbols():
    data = request.get_json(force=True) or {}
    channel_ids = data.get('channel_ids', [])

    q = db.session.query(Trade.symbol).distinct()
    if channel_ids:
        q = q.filter(Trade.channel_id.in_(channel_ids))
    rows = q.order_by(Trade.symbol).all()
    return jsonify({'symbols': [r[0] for r in rows]})


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _parse_float(value) -> Optional[float]:
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _load_trades(filters: dict) -> list:
    """Load Trade ORM objects ordered by entry_time ASC."""
    channel_ids = filters.get('channel_ids', [])
    date_from   = filters.get('date_from')
    date_to     = filters.get('date_to')
    symbol      = filters.get('symbol')
    trade_type  = filters.get('trade_type')

    q = Trade.query

    if channel_ids:
        q = q.filter(Trade.channel_id.in_(channel_ids))

    if date_from:
        try:
            q = q.filter(Trade.entry_time >= datetime.strptime(date_from, '%Y-%m-%d'))
        except ValueError:
            logger.warning("Invalid date_from: %s", date_from)

    if date_to:
        try:
            dt = datetime.strptime(date_to, '%Y-%m-%d') + timedelta(days=1)
            q = q.filter(Trade.entry_time < dt)
        except ValueError:
            logger.warning("Invalid date_to: %s", date_to)

    if symbol and symbol != 'all':
        q = q.filter(Trade.symbol == symbol.upper())

    if trade_type and trade_type != 'all':
        # DECISION-17: individual types only, no grouping
        q = q.filter(Trade.trade_type == trade_type)

    return q.order_by(Trade.entry_time.asc()).all()