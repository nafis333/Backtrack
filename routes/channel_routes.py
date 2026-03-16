"""
routes/channel_routes.py
"""

import logging
from flask import Blueprint, render_template, request, redirect, url_for, \
    jsonify, make_response

# BUG 8 FIX: Removed unused top-level `from db import Channel`.
# Channel is only needed inside delete_trade_route, so it's imported locally there.
from utils.trade_storage import (
    get_all_channel_metas,
    get_all_channels,
    get_channel_by_id,
    get_channel_meta,
    get_trades_by_channel,
    get_channel_filter_options,
    get_channel_detail_context,
    create_channel,
    rename_channel,
    archive_channel,
    unarchive_channel,
    delete_channel,
    delete_trade,
    move_trade,
    export_trades_csv,
)

channel_bp = Blueprint("channel_bp", __name__)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# /channels — Channel List
# ═══════════════════════════════════════════════════════════════

@channel_bp.route("/channels")
def channels_list():
    show_archived = request.args.get("archived", "0") == "1"
    metas = get_all_channel_metas(include_archived=show_archived)
    # BUG 5 FIX: Removed the spurious `all_channels` query here.
    # The "move trade" dropdown belongs on channel_detail, not the list page.
    # Fetching it on every /channels load was a wasted query and sent unused
    # data to channels.html, which has no move-trade UI.
    return render_template(
        "channels.html",
        metas=metas,
        show_archived=show_archived,
    )


# ═══════════════════════════════════════════════════════════════
# POST /channels/create
# ═══════════════════════════════════════════════════════════════

@channel_bp.route("/channels/create", methods=["POST"])
def create_channel_route():
    name        = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    color       = request.form.get("color", "#4A90D9").strip()
    try:
        create_channel(name, description, color)
        return jsonify({"success": True})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("create_channel failed: %s", e)
        return jsonify({"success": False, "error": "Unexpected error."}), 500


# ═══════════════════════════════════════════════════════════════
# POST /channels/<id>/rename
# ═══════════════════════════════════════════════════════════════

@channel_bp.route("/channels/<int:channel_id>/rename", methods=["POST"])
def rename_channel_route(channel_id):
    new_name = request.form.get("name", "").strip()
    try:
        rename_channel(channel_id, new_name)
        return jsonify({"success": True})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("rename_channel failed: %s", e)
        return jsonify({"success": False, "error": "Unexpected error."}), 500


# ═══════════════════════════════════════════════════════════════
# POST /channels/<id>/archive  +  /unarchive
# ═══════════════════════════════════════════════════════════════

@channel_bp.route("/channels/<int:channel_id>/archive", methods=["POST"])
def archive_channel_route(channel_id):
    try:
        archive_channel(channel_id)
        return jsonify({"success": True})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("archive_channel failed: %s", e)
        return jsonify({"success": False, "error": "Unexpected error."}), 500


@channel_bp.route("/channels/<int:channel_id>/unarchive", methods=["POST"])
def unarchive_channel_route(channel_id):
    try:
        unarchive_channel(channel_id)
        return jsonify({"success": True})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("unarchive_channel failed: %s", e)
        return jsonify({"success": False, "error": "Unexpected error."}), 500


# ═══════════════════════════════════════════════════════════════
# POST /channels/<id>/delete
# ═══════════════════════════════════════════════════════════════

@channel_bp.route("/channels/<int:channel_id>/delete", methods=["POST"])
def delete_channel_route(channel_id):
    # BUG 2 FIX: The old `== "1"` check silently treated `force=true`
    # (standard JS boolean serialisation) as False, causing the delete to
    # fail with a ValueError when trades existed — with no clear error.
    force_val = request.form.get("force", "0").strip().lower()
    force = force_val in {"1", "true", "yes"}
    try:
        delete_channel(channel_id, force=force)
        return jsonify({"success": True})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_channel failed: %s", e)
        return jsonify({"success": False, "error": "Unexpected error."}), 500


# ═══════════════════════════════════════════════════════════════
# GET /channels/<id> — Channel Detail
# ═══════════════════════════════════════════════════════════════

@channel_bp.route("/channels/<int:channel_id>")
def channel_detail(channel_id):
    channel = get_channel_by_id(channel_id)
    if not channel:
        return render_template("error.html", error="Channel not found.", traceback=""), 404

    f_symbol     = request.args.get("symbol", "all")
    f_trade_type = request.args.get("trade_type", "all")
    f_outcome    = request.args.get("outcome", "all")
    f_date_from  = request.args.get("date_from", "")
    f_date_to    = request.args.get("date_to", "")

    trades = get_trades_by_channel(
        channel_id,
        symbol     = f_symbol,
        trade_type = f_trade_type,
        outcome    = f_outcome,
        date_from  = f_date_from,
        date_to    = f_date_to,
    )

    # get_channel_detail_context loads ALL (unfiltered) trades exactly once
    # and derives both meta and filter_options from that single list —
    # eliminating the two separate Trade.query.filter_by(channel_id).all()
    # calls that get_channel_meta and get_channel_filter_options previously
    # issued independently, and the second Channel.query.get inside get_channel_meta.
    meta, filter_options = get_channel_detail_context(channel_id)
    all_channels         = get_all_channels(include_archived=False)

    return render_template(
        "channel_detail.html",
        channel        = channel,
        trades         = trades,
        meta           = meta,
        filter_options = filter_options,
        all_channels   = [c for c in all_channels if c.channel_id != channel_id],
        f_symbol       = f_symbol,
        f_trade_type   = f_trade_type,
        f_outcome      = f_outcome,
        f_date_from    = f_date_from,
        f_date_to      = f_date_to,
    )


# ═══════════════════════════════════════════════════════════════
# POST /trades/<id>/delete
# ═══════════════════════════════════════════════════════════════

@channel_bp.route("/trades/<int:trade_id>/delete", methods=["POST"])
def delete_trade_route(trade_id):
    # delete_trade() returns the channel_id as a plain int (captured before
    # db.session.commit() so there is no expire_on_commit / DetachedInstanceError risk).
    # A single Trade.query.get() is still used internally — no race-condition window.
    try:
        channel_id = delete_trade(trade_id)
        return jsonify({"success": True, "channel_id": channel_id})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("delete_trade failed: %s", e)
        return jsonify({"success": False, "error": "Unexpected error."}), 500


# ═══════════════════════════════════════════════════════════════
# POST /trades/<id>/move
# ═══════════════════════════════════════════════════════════════

@channel_bp.route("/trades/<int:trade_id>/move", methods=["POST"])
def move_trade_route(trade_id):
    try:
        new_channel_id = int(request.form.get("channel_id", 0))
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "Invalid channel."}), 400
    try:
        # move_trade returns the new channel_id as a plain int (no post-commit ORM access)
        channel_id = move_trade(trade_id, new_channel_id)
        return jsonify({"success": True, "new_channel_id": channel_id})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("move_trade failed: %s", e)
        return jsonify({"success": False, "error": "Unexpected error."}), 500


# ═══════════════════════════════════════════════════════════════
# POST /trades/<id>/notes — Inline notes update
# ═══════════════════════════════════════════════════════════════

@channel_bp.route("/trades/<int:trade_id>/notes", methods=["POST"])
def update_trade_notes(trade_id):
    """
    Saves notes for a trade without a page reload.
    Called by the drawer's "Save notes" button via fetch().
    """
    from db import db, Trade
    trade = Trade.query.get(trade_id)
    if not trade:
        return jsonify({"success": False, "error": "Trade not found."}), 404
    notes = request.form.get("notes", "").strip() or None
    try:
        trade.notes = notes
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        logger.exception("update_trade_notes failed: %s", e)
        db.session.rollback()
        return jsonify({"success": False, "error": "Unexpected error."}), 500


# POST /trades/<id>/untp-notes — Inline UNTP notes update
# ═══════════════════════════════════════════════════════════════

@channel_bp.route("/trades/<int:trade_id>/untp-notes", methods=["POST"])
def update_untp_notes(trade_id):
    """
    Saves UNTP-specific notes for a trade without a page reload.
    Stored in the separate untp_notes column — independent of trade notes.
    """
    from db import db, Trade
    trade = Trade.query.get(trade_id)
    if not trade:
        return jsonify({"success": False, "error": "Trade not found."}), 404
    notes = request.form.get("notes", "").strip() or None
    try:
        trade.untp_notes = notes
        db.session.commit()
        return jsonify({"success": True})
    except Exception as e:
        logger.exception("update_untp_notes failed: %s", e)
        db.session.rollback()
        return jsonify({"success": False, "error": "Unexpected error."}), 500


# ═══════════════════════════════════════════════════════════════
# GET /channels/<id>/export — CSV Download
# ═══════════════════════════════════════════════════════════════

@channel_bp.route("/channels/<int:channel_id>/export")
def export_channel_csv(channel_id):
    channel = get_channel_by_id(channel_id)
    if not channel:
        return "Channel not found", 404

    csv_str = export_trades_csv(
        channel_id,
        symbol     = request.args.get("symbol"),
        trade_type = request.args.get("trade_type"),
        outcome    = request.args.get("outcome"),
        date_from  = request.args.get("date_from"),
        date_to    = request.args.get("date_to"),
    )

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in channel.name)
    filename  = f"trades_{safe_name}.csv"

    response = make_response(csv_str)
    response.headers["Content-Type"]        = "text/csv; charset=utf-8"
    # Filename must be quoted (RFC 6266) so names with spaces/underscores
    # aren't split by browsers that don't tolerate bare token filenames.
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response