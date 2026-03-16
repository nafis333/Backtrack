import os
import pandas as pd
import logging

# ------------------------------------------------------------------
# 1.  Resolve the “Stored files” directory once and for all
# ------------------------------------------------------------------
def _stored_files_dir() -> str:
    """
    Absolute path to the 'Stored files' folder that lives next to this file
    (or next to the current working directory if run in a notebook).
    """
    base = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    return os.path.join(base, "Stored files")


_STORED_DIR = _stored_files_dir()

# ------------------------------------------------------------------
# 2.  File-name mapping (unchanged)
# ------------------------------------------------------------------
FILE_NAME_MAPPING = {
    "NAS100": "USTEC"
    # Add more if required
}

def get_file_name(symbol: str) -> str:
    """
    Returns the mapped file name if defined; otherwise symbol.upper().
    """
    if not symbol:
        raise ValueError("Symbol cannot be None or an empty string.")
    mapped = FILE_NAME_MAPPING.get(symbol.upper(), symbol.upper())
    if mapped != symbol.upper():
        logging.debug(f"Symbol '{symbol}' mapped to file name '{mapped}'.")
    return mapped

# ------------------------------------------------------------------
# 3.  Data retrieval (no hard-coded paths)
# ------------------------------------------------------------------
def get_closing_price(year, month, day, hour, minute, symbol):
    """
    Return the closing price at or immediately after the specified timestamp
    for the given symbol.  Loads the parquet file from 'Stored files'.
    """
    input_time = pd.Timestamp(year, month, day, hour, minute)
    if not symbol:
        raise ValueError("No symbol provided for closing price retrieval.")

    file_name = get_file_name(symbol)
    file_path = os.path.join(_STORED_DIR, f"{file_name}.parquet")

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Data file for {symbol} not found: {file_path}")

    df = pd.read_parquet(file_path)

    if "Local time" not in df.columns:
        raise ValueError(f"'Local time' column missing in {symbol} dataset.")

    df["Local time"] = pd.to_datetime(df["Local time"], format="%d.%m.%Y %H:%M:%S", errors="coerce")
    df = df.dropna(subset=["Local time"])

    if "Pair" in df.columns:
        df = df[df["Pair"].str.upper() == symbol.upper()]
        if df.empty:
            raise ValueError(f"No matching data found for {symbol}.")

    df_sorted = df.sort_values("Local time")
    df_after = df_sorted[df_sorted["Local time"] >= input_time]

    if df_after.empty:
        if not df_sorted.empty:
            logging.warning(
                f"No data found after {input_time} for {symbol}. Returning last available price."
            )
            return df_sorted.iloc[-1]["Close"]
        else:
            raise ValueError(f"No data available for {symbol}.")

    return df_after.iloc[0]["Close"]

# ------------------------------------------------------------------
# 4.  Pip-calculation utility (unchanged logic)
# ------------------------------------------------------------------
def calculate_pips(entry_price, target_price, symbol):
    """
    Compute the pip distance between two prices for the given symbol.
    """
    if not (isinstance(entry_price, (int, float)) and isinstance(target_price, (int, float))):
        raise ValueError(f"Invalid price input: Entry ({entry_price}), Target ({target_price})")

    if entry_price <= 0 or target_price <= 0:
        raise ValueError("Prices must be greater than zero.")

    symbol = symbol.upper()

    if symbol == "XAUUSD":
        pip_size = 0.1
    elif symbol == "XAGUSD":
        pip_size = 0.01
    elif symbol in {"NAS100", "US30"}:
        pip_size = 1.0
    elif symbol in {"USOIL", "UKOIL"}:
        pip_size = 0.1
    else:
        pip_size = 0.01 if "JPY" in symbol else 0.0001

    return abs(target_price - entry_price) / pip_size