import os
import pandas as pd
import logging
from utils.symbols import SYMBOLS
from utils.trade_calculations import get_file_name

logger = logging.getLogger(__name__)


def _stored_files_dir() -> str:
    base = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    return os.path.join(base, "Stored files")


data_frames = {}
STORED_DIR = _stored_files_dir()

for sym in SYMBOLS:
    file_name = get_file_name(sym)
    file_path = os.path.join(STORED_DIR, f"{file_name}.parquet")
    try:
        df = pd.read_parquet(file_path)

        if 'Local time' not in df.columns:
            raise ValueError(f"'Local time' column is missing in the dataset for {sym}.")

        df['Local time'] = pd.to_datetime(
            df['Local time'],
            format='%d.%m.%Y %H:%M:%S',
            errors='coerce'
        )

        invalid_rows = df['Local time'].isna().sum()
        if invalid_rows > 0:
            logger.warning("%s: Dropped %d rows with invalid 'Local time' values.", sym, invalid_rows)

        df = df.dropna(subset=['Local time'])
        df = df.dropna(subset=['Open', 'High', 'Low', 'Close'])

        if df.empty:
            logger.warning("All rows dropped for %s due to missing price data.", sym)

        data_frames[sym.upper()] = df

    except Exception as e:
        logger.error("Error loading/parsing file for %s from %s: %s", sym, file_path, e)