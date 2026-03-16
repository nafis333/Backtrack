import logging
from datetime import datetime
from utils.pip_utils import get_pip_size  # Import the pip conversion helper

def validate_trade_inputs(entry_price, stoploss_price, takeprofit_price, trade_type, current_price, symbol, limit_price=None):
    """
    Validate trade inputs for a given symbol.
    Raises ValueError if any input is invalid.
    """
    logging.debug(f"Validating trade inputs for {symbol}: entry={entry_price}, stoploss={stoploss_price}, "
                  f"takeprofit={takeprofit_price}, trade_type={trade_type}, current_price={current_price}, "
                  f"limit_price={limit_price}")
    
    # Ensure all prices are valid positive numbers.
    for price in [entry_price, stoploss_price, takeprofit_price]:
        if not isinstance(price, (int, float)) or price <= 0:
            raise ValueError(f"Invalid input: Price value '{price}' for {symbol} is invalid.")
    
    # Check that entry, stop loss, and take profit are distinct.
    if entry_price == stoploss_price:
        raise ValueError("Entry Price and Stop Loss cannot be the same.")
    if entry_price == takeprofit_price:
        raise ValueError("Entry Price and Take Profit cannot be the same.")
    if abs(entry_price - stoploss_price) == 0:
        raise ValueError("Risk amount (difference between Entry and Stop Loss) cannot be zero.")
    
    trade_type = trade_type.lower()
    valid_trade_types = {'buy', 'sell', 'limit_buy', 'limit_sell', 'stop_buy', 'stop_sell'}
    if trade_type not in valid_trade_types:
        raise ValueError("Invalid trade type. Please enter 'Buy', 'Sell', 'Limit Buy', 'Limit Sell', 'Stop Buy', or 'Stop Sell'.")
    
    # Market and Stop Loss / Take Profit Logic
    if trade_type in {'buy', 'limit_buy', 'stop_buy'}:
        if stoploss_price >= entry_price:
            raise ValueError("For Buy/Limit Buy/Stop Buy, Stop Loss must be below the entry price.")
        if takeprofit_price <= entry_price:
            raise ValueError("For Buy/Limit Buy/Stop Buy, Take Profit must be above the entry price.")
    elif trade_type in {'sell', 'limit_sell', 'stop_sell'}:
        if stoploss_price <= entry_price:
            raise ValueError("For Sell/Limit Sell/Stop Sell, Stop Loss must be above the entry price.")
        if takeprofit_price >= entry_price:
            raise ValueError("For Sell/Limit Sell/Stop Sell, Take Profit must be below the entry price.")
    
    # Additional validation for Limit and Stop orders.
    if trade_type in {'limit_buy', 'limit_sell', 'stop_buy', 'stop_sell'}:
        if limit_price is None or not isinstance(limit_price, (int, float)) or limit_price <= 0:
            raise ValueError("A valid limit price must be provided for limit/stop orders.")
        if trade_type == 'limit_buy' and limit_price >= current_price:
            raise ValueError("Limit Buy price must be below the current market price.")
        if trade_type == 'limit_sell' and limit_price <= current_price:
            raise ValueError("Limit Sell price must be above the current market price.")
        if trade_type == 'stop_buy' and limit_price <= current_price:
            raise ValueError("Stop Buy price must be above the current market price.")
        if trade_type == 'stop_sell' and limit_price >= current_price:
            raise ValueError("Stop Sell price must be below the current market price.")
    
    return None

def validate_trade_type(form_data):
    trade_type = form_data.get('trade_type', '').strip().lower()
    valid_trade_types = {'buy', 'sell', 'limit_buy', 'limit_sell', 'stop_buy', 'stop_sell'}
    if trade_type not in valid_trade_types:
        raise ValueError("Invalid trade type.")
    return trade_type

def process_trade_inputs(request, trade_type, entry_time, get_closing_price_func, symbol):
    """
    Process trade inputs from the form for a specific symbol.
    Returns (limit_price, stoploss_price, takeprofit_price, input_type) if valid.
    Raises ValueError with a descriptive message on any error.
    """
    input_type = request.form.get('input_type', '').strip().lower()
    valid_input_types = {'prices', 'pips', 'rr'}
    if input_type not in valid_input_types:
        raise ValueError("Invalid input type.")
    
    # Ensure that the trade is not closed before the entry time
    close_time_str = request.form.get('close_trade_time', '').strip()
    if close_time_str:
            close_time = datetime.strptime(close_time_str, "%Y-%m-%d %H:%M")
            if close_time < entry_time:
                raise ValueError(f"Close trade time {close_time} cannot be earlier than the entry time {entry_time}.")
        
    current_price = get_closing_price_func(
        entry_time.year, entry_time.month, entry_time.day, entry_time.hour, entry_time.minute, symbol
    )
    if current_price is None:
        raise ValueError(f"Could not determine entry price for {symbol} from the given time.")
    
    limit_price = None
    if trade_type in {'limit_buy', 'limit_sell', 'stop_buy', 'stop_sell'}:
        order_str = request.form.get('limit_price', '').strip()
        if not order_str:
            raise ValueError("Order price must be provided for limit/stop orders.")
        try:
            limit_price = float(order_str)
        except ValueError:
            raise ValueError("Invalid order price value.")
    
    entry_price = limit_price if trade_type in {'limit_buy', 'limit_sell', 'stop_buy', 'stop_sell'} else current_price
    
    try:
        multiplier = 1 if trade_type in {'buy', 'limit_buy', 'stop_buy'} else -1
        if input_type == 'prices':
            stoploss_price = float(request.form.get('stoploss_price', '0'))
            takeprofit_price = float(request.form.get('takeprofit_price', '0'))
        elif input_type == 'pips':
            stoploss_pips = float(request.form.get('stoploss_pips', '0'))
            takeprofit_pips = float(request.form.get('takeprofit_pips', '0'))
            if stoploss_pips <= 0 or takeprofit_pips <= 0:
                raise ValueError("Pip values must be positive.")
            pip_size = get_pip_size(symbol)
            stoploss_price = entry_price - (stoploss_pips * pip_size * multiplier)
            takeprofit_price = entry_price + (takeprofit_pips * pip_size * multiplier)
        elif input_type == 'rr':
            stoploss_type = request.form.get('stoploss_type_rr', '').strip()
            if stoploss_type == 'price':
                stoploss_price = float(request.form.get('stoploss_price_rr', '0'))
            elif stoploss_type == 'pips':
                stoploss_pips = float(request.form.get('stoploss_pips_rr', '0'))
                if stoploss_pips <= 0:
                    raise ValueError("Stop Loss pips must be positive.")
                pip_size = get_pip_size(symbol)
                stoploss_price = entry_price - (stoploss_pips * pip_size * multiplier)
            else:
                raise ValueError("Invalid Stop Loss type.")
            rr_ratio = float(request.form.get('rr_ratio', '0'))
            if rr_ratio <= 0:
                raise ValueError("Invalid Risk-Reward ratio.")
            risk_amount = abs(entry_price - stoploss_price)
            if risk_amount == 0:
                raise ValueError("Risk amount cannot be zero.")
            takeprofit_price = entry_price + (risk_amount * rr_ratio * multiplier)
        else:
            raise ValueError("Invalid trade input.")
    except ValueError as e:
        raise ValueError("Invalid trade input values.") from e

    validate_trade_inputs(
        entry_price=entry_price, 
        stoploss_price=stoploss_price, 
        takeprofit_price=takeprofit_price, 
        trade_type=trade_type, 
        current_price=current_price,
        symbol=symbol,
        limit_price=limit_price
    )
    return limit_price, stoploss_price, takeprofit_price, input_type

def validate_breakeven_input(request):
    """
    Validate the breakeven flag and, if enabled, the breakeven input.
    Returns a tuple: (breakeven, breakeven_type, breakeven_value) where:
      - breakeven is a boolean,
      - breakeven_type is 'rr' or 'pips',
      - breakeven_value is the corresponding RR ratio or pip value.
    Raises ValueError if enabled but missing or invalid.
    """
    breakeven_input = request.form.get('breakeven', '').strip().lower()
    breakeven = breakeven_input in {'true', '1', 'yes'}
    if not breakeven:
        return breakeven, None, None
    breakeven_type = request.form.get('breakeven_type', '').strip().lower()
    if breakeven_type not in {'rr', 'pips'}:
        raise ValueError("Invalid breakeven type. Must be 'rr' or 'pips'.")
    if breakeven_type == 'rr':
        value_str = request.form.get('breakeven_rr', '').strip()
        if not value_str:
            raise ValueError("Breakeven RR must be provided when breakeven type is RR.")
        try:
            value = float(value_str)
            if value <= 0:
                raise ValueError("Breakeven RR must be greater than zero.")
        except ValueError:
            raise ValueError("Invalid Breakeven RR.")
    else:  # pips
        value_str = request.form.get('breakeven_pips', '').strip()
        if not value_str:
            raise ValueError("Breakeven pips must be provided when breakeven type is pips.")
        try:
            value = float(value_str)
            if value <= 0:
                raise ValueError("Breakeven pips must be greater than zero.")
        except ValueError:
            raise ValueError("Invalid Breakeven pips.")
    return breakeven, breakeven_type, value

def validate_expiry_input(request, trade_type):
    """
    Validate expiry inputs for pending orders.
    Returns (expiry_enabled, expiry_days, expiry_hours, expiry_minutes).
    Raises ValueError if any expiry field is missing or invalid.
    """
    if trade_type in {'limit_buy', 'limit_sell', 'stop_buy', 'stop_sell'}:
        expiry_enabled = request.form.get('expiry_enabled', '').strip().lower()
        if expiry_enabled not in {'true', 'false'}:
            raise ValueError("Expiry enabled field must be selected as true or false.")
        if expiry_enabled == 'false':
            return False, 0, 0, 0
        expiry_days_str = request.form.get('expiry_days', '').strip()
        expiry_hours_str = request.form.get('expiry_hours', '').strip()
        expiry_minutes_str = request.form.get('expiry_minutes', '').strip()
        if not expiry_days_str or not expiry_hours_str or not expiry_minutes_str:
            raise ValueError("All expiry fields are required when expiry is enabled for pending orders.")
        try:
            expiry_days = int(expiry_days_str)
            expiry_hours = int(expiry_hours_str)
            expiry_minutes = int(expiry_minutes_str)
        except ValueError:
            raise ValueError("Expiry fields must be valid numbers.")
        if expiry_days < 0 or expiry_hours < 0 or expiry_minutes < 0:
            raise ValueError("Expiry fields must be non-negative.")
        if expiry_days == 0 and expiry_hours == 0 and expiry_minutes == 0:
            raise ValueError("Expiry duration cannot be zero if expiry is enabled.")
        return True, expiry_days, expiry_hours, expiry_minutes
    else:
        # For market orders, expiry is ignored.
        return False, 0, 0, 0
