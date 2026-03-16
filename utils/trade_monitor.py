import logging
from datetime import timedelta
from utils.trade_calculations import calculate_pips, get_closing_price
from utils.trade_validation import validate_trade_inputs
from data_loader import data_frames  # Dictionary of preloaded DataFrames keyed by symbol

# Updated runtime formatter: converts timedelta to a "XD YH ZM" format.
def format_runtime(runtime):
    days = runtime.days
    hours = runtime.seconds // 3600
    minutes = (runtime.seconds % 3600) // 60
    return f"{days}D {hours}H {minutes}M"

def get_pip_size(symbol):
    """
    Returns the pip size for the given symbol.
      - XAUUSD: 0.1
      - XAGUSD: 0.01
      - NAS100/US30: 1.0
      - USOIL/UKOIL: 0.1
      - Forex: If symbol contains "JPY", return 0.01; otherwise, 0.0001.
    """
    sym = symbol.upper()
    if sym == "XAUUSD":
        return 0.1
    elif sym == "XAGUSD":
        return 0.01
    elif sym in {"NAS100", "US30"}:
        return 1.0
    elif sym in {"USOIL", "UKOIL"}:
        return 0.1
    else:
        return 0.01 if "JPY" in sym else 0.0001

def monitor_trade(entry_time, stoploss_price, takeprofit_price, trade_type, breakeven, symbol, 
                  breakeven_rr=1.0, breakeven_type='rr', breakeven_pips=None,
                  limit_price=None, stop_limit_execution_price=None,
                  expiry_days=0, expiry_hours=0, expiry_minutes=0, close_trade_time=None):
    """
    Monitor the trade based on provided parameters for a specific trading symbol.
    Handles market, limit, stop, and stop-limit orders while validating execution.
    
    For pending orders (limit, stop, stop-limit), an expiry time is applied if provided.
    If expiry is disabled (expiry_days/hours/minutes all 0), the expiry check is ignored.
    A user-specified close_trade_time forces evaluation at that moment.
    
    The function checks for trade terminal events (TP, SL, or breakeven) before close_trade_time.
    For stop-limit orders, both a stop trigger price and an execution limit price must be provided.
    """
    # Validate symbol.
    if not symbol:
        raise ValueError("No symbol provided.")
    
    if symbol not in data_frames:
        raise ValueError(f"No data available for symbol: {symbol}")
    df = data_frames[symbol]

    # Validate close_trade_time if provided.
    if close_trade_time and close_trade_time <= entry_time:
        raise ValueError("Close trade time is invalid: it is earlier than the entry time.")

    # Get the initial market price at entry.
    current_price = get_closing_price(
        entry_time.year, entry_time.month, entry_time.day,
        entry_time.hour, entry_time.minute, symbol
    )
    if current_price is None:
        raise ValueError(f"No data found for the specified entry time for {symbol}.")
    logging.debug(f"Current market price for {symbol} at entry: {current_price:.5f}")
    entry_price = current_price

    # Pre-validation for pending orders.
    if trade_type == 'limit_buy' and limit_price > current_price:
        raise ValueError("For Limit Buy, limit price must be <= current price.")
    elif trade_type == 'limit_sell' and limit_price < current_price:
        raise ValueError("For Limit Sell, limit price must be >= current price.")
    elif trade_type == 'stop_buy' and limit_price <= current_price:
        raise ValueError("For Stop Buy, stop price must be > current price.")
    elif trade_type == 'stop_sell' and limit_price >= current_price:
        raise ValueError("For Stop Sell, stop price must be < current price.")
    elif trade_type in {'stop_limit_buy', 'stop_limit_sell'}:
        if limit_price is None or stop_limit_execution_price is None:
            raise ValueError("For Stop-Limit orders, both stop trigger and execution limit prices must be provided.")
        if trade_type == 'stop_limit_buy':
            if limit_price <= current_price:
                raise ValueError("For Stop Limit Buy, stop trigger price must be > current price.")
            if stop_limit_execution_price > limit_price:
                raise ValueError("For Stop Limit Buy, execution limit price must be <= stop trigger price.")
        else:  # stop_limit_sell
            if limit_price >= current_price:
                raise ValueError("For Stop Limit Sell, stop trigger price must be < current price.")
            if stop_limit_execution_price < limit_price:
                raise ValueError("For Stop Limit Sell, execution limit price must be >= stop trigger price.")

    # Additional validation for trade inputs.
    if trade_type in {'limit_buy', 'stop_buy', 'stop_limit_buy'} and stoploss_price >= limit_price:
        raise ValueError("Invalid Stop Loss: It should be below the entry price for buy orders.")
    if trade_type in {'limit_sell', 'stop_sell', 'stop_limit_sell'} and stoploss_price <= limit_price:
        raise ValueError("Invalid Stop Loss: It should be above the entry price for sell orders.")

    # Filter and sort candle data after the entry time.
    df_filtered = df[df['Local time'] > entry_time].sort_values('Local time')
    if df_filtered.empty:
        raise ValueError(f"No data available after the specified entry time for {symbol}.")

    pending_order_start_time = entry_time
    pending_order_runtime = None
    logging.debug(f"Expiry inputs received: days={expiry_days}, hours={expiry_hours}, minutes={expiry_minutes}")

    # Handle pending orders.
    if trade_type in {'limit_buy', 'limit_sell', 'stop_buy', 'stop_sell', 'stop_limit_buy', 'stop_limit_sell'}:
        # If any expiry value is non-zero, set an expiry time; otherwise, ignore expiry.
        if expiry_days or expiry_hours or expiry_minutes:
            expiry_duration = timedelta(days=expiry_days, hours=expiry_hours, minutes=expiry_minutes)
            expiry_time = pending_order_start_time + expiry_duration
            logging.debug(f"Pending order will expire at: {expiry_time.strftime('%I:%M %p (%d %B %Y)')}")
        else:
            expiry_time = None

        triggered = False
        prev_row = None
        for index, row in df_filtered.iterrows():
            candle_time = row['Local time']
            # Check for user-specified close_trade_time.
            if close_trade_time and candle_time >= close_trade_time and not triggered:
                current_price_at_close = row['Close']
                runtime = close_trade_time - pending_order_start_time
                formatted_runtime = format_runtime(runtime)
                return [
                    f"Pending Order Not Triggered by Close Trade Time {close_trade_time.strftime('%I:%M %p (%d %B %Y)')}",
                    f"Current Price: {current_price_at_close:.5f} | Runtime: {formatted_runtime}"
                ]
            # Check for expiry if set.
            if expiry_time is not None and candle_time >= expiry_time:
                raise ValueError(f"Order expired at {expiry_time.strftime('%I:%M %p (%d %B %Y)')} without a trigger. "
                                 f"(Expiry: {format_runtime(timedelta(days=expiry_days, hours=expiry_hours, minutes=expiry_minutes))})")
            if prev_row is None:
                prev_row = row
                continue
            # Determine if the candle triggered the order.
            if trade_type in {'stop_buy', 'stop_limit_buy'}:
                if prev_row['Close'] < limit_price and limit_price <= max(row['Open'], row['High'], row['Close']):
                    triggered = True
            elif trade_type in {'stop_sell', 'stop_limit_sell'}:
                if prev_row['Close'] > limit_price and limit_price >= min(row['Open'], row['Low'], row['Close']):
                    triggered = True
            elif trade_type == 'limit_buy':
                if min(row['Open'], row['Low'], row['Close']) <= limit_price:
                    triggered = True
            elif trade_type == 'limit_sell':
                if max(row['Open'], row['High'], row['Close']) >= limit_price:
                    triggered = True

            if triggered:
                pending_order_runtime = candle_time - pending_order_start_time
                # Log and set the entry price based on the type.
                if trade_type in {'stop_limit_buy', 'stop_limit_sell'}:
                    logging.info(f"{trade_type.capitalize()} triggered at {candle_time.strftime('%I:%M %p (%d %B %Y)')}, execution price: {stop_limit_execution_price:.5f}")
                    entry_price = stop_limit_execution_price
                else:
                    logging.info(f"{trade_type.capitalize()} triggered at {candle_time.strftime('%I:%M %p (%d %B %Y)')}, limit price: {limit_price:.5f}")
                    entry_price = limit_price
                # Update entry_time to the trigger time.
                entry_time = candle_time
                df_filtered = df[df['Local time'] > entry_time].sort_values('Local time')
                break
            prev_row = row

        if not triggered:
            if expiry_time is not None:
                raise ValueError(f"Order expired at {expiry_time.strftime('%I:%M %p (%d %B %Y)')} without a trigger. "
                                 f"(Expiry: {format_runtime(timedelta(days=expiry_days, hours=expiry_hours, minutes=expiry_minutes))})")
            else:
                # If no expiry is set, simply continue.
                pass

    base_trade = trade_type.replace("limit_", "").replace("stop_", "").replace("stop_limit_", "")
    logging.debug(f"Base trade type: {base_trade}")
    
    # Validate trade inputs.
    validation_error = validate_trade_inputs(
        entry_price=entry_price, 
        stoploss_price=stoploss_price, 
        takeprofit_price=takeprofit_price, 
        trade_type=base_trade, 
        current_price=current_price,
        limit_price=limit_price,
        symbol=symbol
    )
    if validation_error:
        raise ValueError(validation_error)
    
    sl_pips = calculate_pips(entry_price, stoploss_price, symbol)
    tp_pips = calculate_pips(entry_price, takeprofit_price, symbol)
    
    results = []
    results.append(f"Pair: {symbol}")
    order_type_desc = ""
    if trade_type in {'limit_buy', 'limit_sell'}:
        order_type_desc = "(Limit)"
    elif trade_type in {'stop_buy', 'stop_sell'}:
        order_type_desc = "(Stop)"
    elif trade_type in {'stop_limit_buy', 'stop_limit_sell'}:
        order_type_desc = "(Stop-Limit)"
    results.append(f"Trade Type: {base_trade.capitalize()} {order_type_desc}")
    results.append(f"Entry Price: {entry_price:.5f} | Time: {entry_time.strftime('%I:%M %p (%d %B %Y)')}")
    results.append(f"SL Price: {stoploss_price:.5f} ({sl_pips:.2f} pips) | TP Price: {takeprofit_price:.5f} ({tp_pips:.2f} pips)")
    
    # Append pending order triggered message with expiry info (only once) if applicable.
    if trade_type in {'limit_buy', 'limit_sell', 'stop_buy', 'stop_sell', 'stop_limit_buy', 'stop_limit_sell'} and pending_order_runtime is not None:
        pending_order_runtime_str = format_runtime(pending_order_runtime)
        trigger_date_str = entry_time.strftime('%I:%M %p (%d %B %Y)')
        if expiry_days or expiry_hours or expiry_minutes:
            expiry_duration_str = format_runtime(timedelta(days=expiry_days, hours=expiry_hours, minutes=expiry_minutes))
            results.append(f"Pending Order Triggered after: {pending_order_runtime_str} on {trigger_date_str} (Expiry: {expiry_duration_str})")
        else:
            results.append(f"Pending Order Triggered after: {pending_order_runtime_str} on {trigger_date_str}")
    
    logging.debug("Starting trade monitoring loop for SL/TP conditions.")
    breakeven_triggered = False
    original_sl = stoploss_price
    initial_risk = abs(entry_price - original_sl)
    
    for index, row in df_filtered.iterrows():
        current_high = row['High']
        current_low = row['Low']
        current_time = row['Local time']
        runtime = current_time - entry_time
        formatted_runtime = format_runtime(runtime)
        logging.debug(f"At {current_time}: High={current_high}, Low={current_low}, Runtime={formatted_runtime}")
    
        if base_trade == 'buy':
            if current_high >= takeprofit_price:
                results.append(f"TP Hit: {takeprofit_price:.5f} | Time: {current_time.strftime('%I:%M %p (%d %B %Y)')} | Runtime: {formatted_runtime}")
                results.append(f"PnL: {tp_pips / sl_pips:.2f}R" if sl_pips else "PnL: N/A")
                return results
            if current_low <= stoploss_price:
                if breakeven_triggered:
                    results.append(f"Breakeven Hit: {stoploss_price:.5f} | Time: {current_time.strftime('%I:%M %p (%d %B %Y)')} | Runtime: {formatted_runtime}")
                    results.append("PnL: 0R")
                else:
                    results.append(f"SL Hit: {stoploss_price:.5f} | Time: {current_time.strftime('%I:%M %p (%d %B %Y)')} | Runtime: {formatted_runtime}")
                    results.append("PnL: -1R")
                return results
        else:  # Sell trade.
            if current_low <= takeprofit_price:
                results.append(f"TP Hit: {takeprofit_price:.5f} | Time: {current_time.strftime('%I:%M %p (%d %B %Y)')} | Runtime: {formatted_runtime}")
                results.append(f"PnL: {tp_pips / sl_pips:.2f}R" if sl_pips else "PnL: N/A")
                return results
            if current_high >= stoploss_price:
                if breakeven_triggered:
                    results.append(f"Breakeven Hit: {stoploss_price:.5f} | Time: {current_time.strftime('%I:%M %p (%d %B %Y)')} | Runtime: {formatted_runtime}")
                    results.append("PnL: 0R")
                else:
                    results.append(f"SL Hit: {stoploss_price:.5f} | Time: {current_time.strftime('%I:%M %p (%d %B %Y)')} | Runtime: {formatted_runtime}")
                    results.append("PnL: -1R")
                return results
    
        if breakeven and not breakeven_triggered:
            if breakeven_type == 'rr':
                breakeven_level = (entry_price + (initial_risk * breakeven_rr)) if base_trade == 'buy' else (entry_price - (initial_risk * breakeven_rr))
                trigger_desc = f"{breakeven_rr}R Level"
            elif breakeven_type == 'pips':
                if breakeven_pips is None:
                    raise ValueError("Breakeven pips value must be provided when breakeven type is pips.")
                pip_size = get_pip_size(symbol)
                breakeven_level = (entry_price + (breakeven_pips * pip_size)) if base_trade == 'buy' else (entry_price - (breakeven_pips * pip_size))
                trigger_desc = f"{breakeven_pips} pips offset"
            else:
                raise ValueError("Invalid breakeven type. Must be 'rr' or 'pips'.")
            logging.debug(f"Breakeven check: Level={breakeven_level:.5f}, High={current_high}, Low={current_low}")
            if (base_trade == 'buy' and current_high >= breakeven_level) or (base_trade == 'sell' and current_low <= breakeven_level):
                breakeven_triggered = True
                stoploss_price = entry_price
                results.append(f"Breakeven Activated at {trigger_desc} ({breakeven_level:.5f}) | Time: {current_time.strftime('%I:%M %p (%d %B %Y)')} | Runtime: {formatted_runtime}")
                results.append(f"Breakeven SL set at {entry_price:.5f}")
    
        if close_trade_time and current_time >= close_trade_time:
            results.append(f"Trade evaluated at close time {close_trade_time.strftime('%I:%M %p (%d %B %Y)')}")
            current_price_at_close = row['Close']
            runtime_close = format_runtime(close_trade_time - entry_time)
            current_pips = calculate_pips(entry_price, current_price_at_close, symbol)
            current_rr = current_pips / sl_pips if sl_pips else None
            if current_rr is not None:
                results.append(f"Current Price: {current_price_at_close:.5f} | Runtime: {runtime_close} | PnL: {current_pips:.2f} pips, {current_rr:.2f}R")
            else:
                results.append(f"Current Price: {current_price_at_close:.5f} | Runtime: {runtime_close} | PnL: {current_pips:.2f} pips")
            return results
    
    last_row = df_filtered.iloc[-1]
    current_time = last_row['Local time']
    results.append(f"Trade still running as of {current_time.strftime('%I:%M %p (%d %B %Y)')}")
    results.append(f"Current Price: {last_row['Close']:.5f} | Runtime: {format_runtime(current_time - entry_time)}")
    return results
