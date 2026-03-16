"""
tests/conftest.py
-----------------
Root test configuration for the Backtrack mfe_calculator test suite.

PROJECT STRUCTURE (real layout on disk)
----------------------------------------
backtest app/           ← pytest rootdir (pytest.ini lives here)
  app.py
  data_loader.py        ← root level
  db.py
  pytest.ini
  utils/
    mfe_calculator.py   ← imported as utils.mfe_calculator
    pip_utils.py
    ...
  routes/
    ...
  tests/
    conftest.py         ← this file
    helpers.py
    test_01_*.py

CRITICAL IMPORT ORDER
---------------------
utils.mfe_calculator does at module level:
    from data_loader import data_frames

data_loader tries to read parquet files on import. We inject a mock into
sys.modules["data_loader"] BEFORE importing mfe_calculator so parquet I/O
never fires. This must happen at conftest module level (not inside a fixture).

We do NOT mock utils.pip_utils — the ImportError fires naturally and
mfe_calculator uses its own local fallback (identical to pip_utils.py).

Fixtures
--------
mock_streak (autouse=True)
    Patches _compute_streak to return 0. Avoids DB deps in walk tests.
    test_10_streak.py overrides this per-test.

clean_data_frames (autouse=True)
    Clears mfe_calculator.data_frames before/after every test.

inject_candles (function-scoped, NOT autouse)
    Returns callable inject(symbol, df) for loading synthetic candles.
"""

import sys
import pytest
from unittest.mock import MagicMock
from datetime import datetime

# ── 1. Inject mock data_loader BEFORE mfe_calculator is imported ───────────────
# Must happen at module level. pytest.ini pythonpath=. puts the project root on
# sys.path so data_loader (root-level module) would be found — but we intercept
# it here before it can run its parquet-loading startup code.

_mock_data_loader = MagicMock()
_mock_data_loader.data_frames = {}   # real dict — mfe_calculator binds to this
sys.modules["data_loader"] = _mock_data_loader

# ── 2. Import mfe_calculator ───────────────────────────────────────────────────
# Real project: utils/mfe_calculator.py  → import as utils.mfe_calculator
# Flat layout (container/CI): mfe_calculator.py → import as mfe_calculator
try:
    import utils.mfe_calculator as mfe_calculator
except ModuleNotFoundError:
    import mfe_calculator  # type: ignore[no-redef]

# ── 3. Shared constants ────────────────────────────────────────────────────────
ENTRY_TIME = datetime(2024, 1, 15, 10, 0, 0)


# ── 4. Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_data_frames():
    """Clear data_frames before and after every test — no candle bleed."""
    mfe_calculator.data_frames.clear()
    yield
    mfe_calculator.data_frames.clear()


@pytest.fixture(autouse=True)
def mock_streak(monkeypatch):
    """
    Patch _compute_streak to return 0 for all walk tests.
    test_10_streak.py re-patches per-test with controlled return values.
    """
    monkeypatch.setattr(mfe_calculator, "_compute_streak", lambda channel_id: 0)


@pytest.fixture
def inject_candles():
    """
    Returns a callable inject(symbol, df) that writes a DataFrame into
    mfe_calculator.data_frames. Cleanup handled by clean_data_frames.
    """
    def _inject(symbol: str, df):
        mfe_calculator.data_frames[symbol.upper()] = df
    return _inject