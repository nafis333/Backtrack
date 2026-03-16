from calendar import monthrange
import pandas as pd

from calendar import monthrange
import pandas as pd

def validate_datetime_input(form_data):
    """
    Convert form date/time inputs to a pd.Timestamp.
    Returns a tuple (timestamp, error_message). If valid, error_message is None.
    """
    try:
        year = int(form_data['year'])
        month = int(form_data['month'])
        day = int(form_data['day'])
        hour = int(form_data['hour'])
        minute = int(form_data['minute'])

        if not (1 <= month <= 12) or not (0 <= hour <= 23) or not (0 <= minute <= 59):
            return None, "Invalid date/time values."

        _, days_in_month = monthrange(year, month)
        if not (1 <= day <= days_in_month):
            return None, "Invalid day for the selected month."

        return pd.Timestamp(year, month, day, hour, minute), None

    except (ValueError, KeyError):
        return None, "Invalid date/time input."

def format_runtime(runtime):
    """
    Format a timedelta into a string in the form "XD YH ZMin".
    """
    days = runtime.days
    hours, remainder = divmod(runtime.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    
    formatted_runtime = ""
    formatted_runtime += f"{days}D " if days > 0 or (days == 0 and (hours > 0 or minutes > 0)) else ""
    formatted_runtime += f"{hours}H " if hours > 0 or (hours == 0 and minutes > 0) else ""
    formatted_runtime += f"{minutes}Min"
    
    return formatted_runtime.strip()
