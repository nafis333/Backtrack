from flask import Flask, render_template, request, send_from_directory
import logging
import traceback
from datetime import datetime
from config import SECRET_KEY
from utils.datetime_utils import validate_datetime_input
from utils.trade_calculations import get_closing_price
from utils.trade_validation import (
    validate_trade_type,
    process_trade_inputs,
    validate_breakeven_input,
    validate_expiry_input
)
from utils.trade_monitor import monitor_trade
from utils.symbols import SYMBOLS
from db import init_db
from routes.save_routes import save_bp
from routes.channel_routes import channel_bp
from routes.statistics_routes import stats_bp
import os

app = Flask(__name__)
app.secret_key = SECRET_KEY

init_db(app)
app.register_blueprint(save_bp)
app.register_blueprint(channel_bp)
app.register_blueprint(stats_bp)

# Suppress all INFO logs (parquet loader, trade monitor, etc.)
# Only WARNING+ from app code; werkzeug keeps INFO so the web address still prints.
logging.basicConfig(level=logging.WARNING,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logging.getLogger('werkzeug').setLevel(logging.INFO)
logger = logging.getLogger(__name__)


@app.errorhandler(Exception)
def handle_exception(e):
    tb = traceback.format_exc()
    logger.exception("Unhandled exception: %s", e)
    return render_template("error.html", error=str(e), traceback=tb), 500


@app.route('/favicon.ico')
def favicon():
    p = os.path.join(app.root_path, 'static', 'favicon.ico')
    if os.path.exists(p):
        return send_from_directory(os.path.join(app.root_path, 'static'),
                                   'favicon.ico', mimetype='image/vnd.microsoft.icon')
    return '', 204


@app.route('/')
def index():
    return render_template('index.html', symbols=SYMBOLS)


@app.route('/monitor_trade', methods=['POST'])
def monitor_trade_route():
    logger.info("Processing new trade monitoring request")

    symbol = request.form.get('symbol', '').strip().upper()
    if not symbol or symbol not in SYMBOLS:
        raise ValueError("Please select a valid trading symbol.")

    entry_time, dt_error = validate_datetime_input(request.form)
    if dt_error:
        return render_template("error.html", error=dt_error,
                               error_type="Validation Error",
                               error_location="Datetime Input",
                               stack_trace="No traceback available")

    trade_type = validate_trade_type(request.form)

    limit_price, stoploss_price, takeprofit_price, input_type = process_trade_inputs(
        request=request, trade_type=trade_type, entry_time=entry_time,
        get_closing_price_func=get_closing_price, symbol=symbol
    )

    breakeven, breakeven_type, breakeven_value = validate_breakeven_input(request)

    expiry_enabled, expiry_days, expiry_hours, expiry_minutes = validate_expiry_input(request, trade_type)
    if not expiry_enabled:
        expiry_days, expiry_hours, expiry_minutes = 0, 0, 0

    close_trade_time = None
    close_time_str = request.form.get('close_trade_time', '').strip()
    if close_time_str:
        try:
            close_trade_time = datetime.strptime(close_time_str, '%Y-%m-%d %H:%M')
            if close_trade_time <= entry_time:
                raise ValueError("Close time must be after entry time.")
        except ValueError:
            raise ValueError("Invalid close time format (use YYYY-MM-DD HH:MM).")

    results = monitor_trade(
        entry_time=entry_time,
        stoploss_price=stoploss_price,
        takeprofit_price=takeprofit_price,
        trade_type=trade_type,
        breakeven=breakeven,
        symbol=symbol,
        breakeven_rr=breakeven_value if breakeven_type == 'rr' else 1.0,
        breakeven_type=breakeven_type,
        breakeven_pips=breakeven_value if breakeven_type == 'pips' else None,
        limit_price=limit_price,
        expiry_days=expiry_days,
        expiry_hours=expiry_hours,
        expiry_minutes=expiry_minutes,
        close_trade_time=close_trade_time
    )

    # ── Extract actual entry price from the monitor results string ────────────
    # The results list is plain-text lines from trade_monitor.py. We look for
    # the "Entry Price:" line and parse the value before any "|" separator.
    #
    # Fallback chain:
    #   1. Parse from results string (normal path).
    #   2. For pending orders: use limit_price directly — it IS the fill price.
    #   3. For market orders: re-derive via get_closing_price.
    #   4. If all fail: leave as "" — save_routes._parse_form will raise a
    #      clear ValueError ("entry_price missing or could not be determined")
    #      rather than a cryptic float() exception.
    actual_entry_price = ""

    for line in results:
        if line.startswith("Entry Price:"):
            try:
                actual_entry_price = float(line.split("|")[0].split(":")[1].strip())
            except Exception:
                logger.warning(
                    "Could not parse actual_entry_price from results line '%s' "
                    "for %s — will attempt fallback.", line, symbol
                )
            break

    # Fallback 1: pending orders — limit_price is the exact fill price
    if actual_entry_price == "" and limit_price is not None:
        actual_entry_price = limit_price
        logger.info(
            "Used limit_price (%.5f) as fallback entry_price for %s %s",
            limit_price, symbol, trade_type
        )

    # Fallback 2: market orders — re-derive the closing price at entry_time
    if actual_entry_price == "" and trade_type in ("buy", "sell"):
        try:
            actual_entry_price = get_closing_price(symbol, entry_time)
            logger.info(
                "Re-derived entry_price (%.5f) via get_closing_price for %s",
                actual_entry_price, symbol
            )
        except Exception as e:
            logger.warning(
                "get_closing_price fallback also failed for %s: %s", symbol, e
            )

    save_context = {
        "symbol":           symbol,
        "trade_type":       trade_type,
        "entry_time":       entry_time.strftime("%Y-%m-%d %H:%M"),
        "entry_price":      actual_entry_price,
        "stoploss_price":   stoploss_price,
        "takeprofit_price": takeprofit_price if takeprofit_price is not None else "",
        "limit_price":      limit_price      if limit_price      is not None else "",
        "breakeven_active": "true" if breakeven else "false",
        "breakeven_type":   breakeven_type   if breakeven_type   else "",
        "breakeven_value":  breakeven_value  if breakeven_value  is not None else "",
        "input_type":       input_type,
    }

    return render_template('results.html', results=results, save_context=save_context)


if __name__ == '__main__':
    app.debug = True
    os.environ["FLASK_ENV"] = "development"
    os.environ["FLASK_DEBUG"] = "1"
    app.run(host="0.0.0.0", port=5000, use_reloader=True, use_debugger=True)