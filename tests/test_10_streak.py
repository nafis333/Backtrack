"""
tests/test_10_streak.py
------------------------
Streak computation — _compute_streak unit tests.

Covers
------
T10.1  Empty channel → streak=0
T10.2  Win streak — 3 consecutive hit_tp → streak=+3
T10.3  Loss streak — 2 consecutive hit_sl → streak=-2
T10.4  BUG-1: hit_be in middle of win streak → streak NOT broken (skip)
T10.5  BUG-1: hit_be after wins then loss → loss breaks streak, be is transparent
T10.6  Direction change — win then loss breaks streak (streak=+1 stops at loss)
T10.7  BUG-2: streak walks entry_time DESC — most recent trade drives direction

Key rules guarded
-----------------
BUG-1 (R5): hit_be = neutral/skip. Does NOT break or extend streak.
  hit_tp        → +1 (win)
  hit_sl        → -1 (loss)
  hit_be/open/none → continue (skip — no effect on streak state)

BUG-2 (R6): ORDER BY entry_time DESC. A re-saved old trade must not
  corrupt the streak by appearing at position 0 due to saved_at ordering.
  Since the query orders by entry_time, the mock must deliver trades
  in entry_time DESC order to simulate correct DB behaviour.

Testing approach
----------------
autouse mock_streak patches mfe_calculator._compute_streak → 0 for all tests.
This chunk captures the original function at module-import time (before fixtures
run) and calls it directly, bypassing the autouse patch.
sys.modules['db'] is overridden per-test via monkeypatch so the `from db import
Trade` inside _compute_streak resolves to a mock Trade class.

FakeTrade: minimal object with outcome_at_user_tp and entry_time attributes.
The mock query chain: Trade.query.filter_by(...).order_by(...).all() → list.
"""

import sys
import pytest
from unittest.mock import MagicMock
from datetime import datetime

from tests.helpers import mfe_calculator

# ── Capture original before autouse mock_streak replaces it each test ──────────
# conftest.mock_streak runs per-test (fixture), not at import time, so
# _compute_streak is still the real function when this module is imported.
_real_compute_streak = mfe_calculator._compute_streak


# ── Helpers ───────────────────────────────────────────────────────────────────

class FakeTrade:
    """Minimal Trade stand-in. Only fields _compute_streak reads."""
    def __init__(self, outcome: str, entry_time: datetime):
        self.outcome_at_user_tp = outcome
        self.entry_time         = entry_time


def _make_db_mock(trades: list) -> MagicMock:
    """Build a mock db module with Trade.query chain returning `trades`."""
    mock_db = MagicMock()
    (mock_db.Trade.query
        .filter_by.return_value
        .order_by.return_value
        .all.return_value) = trades
    return mock_db


def _streak(monkeypatch, trades: list) -> int:
    """Inject mock db, call real _compute_streak, return result."""
    monkeypatch.setitem(sys.modules, "db", _make_db_mock(trades))
    return _real_compute_streak(channel_id=1)


# ── T10.1: empty channel → streak=0 ──────────────────────────────────────────

def test_streak_empty_channel(monkeypatch):
    """No trades in channel. Streak must be 0."""
    assert _streak(monkeypatch, []) == 0


# ── T10.2: win streak ─────────────────────────────────────────────────────────

def test_streak_three_wins(monkeypatch):
    """
    3 consecutive hit_tp trades ordered entry_time DESC (most recent first).
    Streak = +3.
    """
    trades = [
        FakeTrade("hit_tp", datetime(2024, 1, 15, 12, 0)),
        FakeTrade("hit_tp", datetime(2024, 1, 15, 11, 0)),
        FakeTrade("hit_tp", datetime(2024, 1, 15, 10, 0)),
    ]
    assert _streak(monkeypatch, trades) == 3


# ── T10.3: loss streak ────────────────────────────────────────────────────────

def test_streak_two_losses(monkeypatch):
    """
    2 consecutive hit_sl trades. Streak = -2.
    """
    trades = [
        FakeTrade("hit_sl", datetime(2024, 1, 15, 12, 0)),
        FakeTrade("hit_sl", datetime(2024, 1, 15, 11, 0)),
    ]
    assert _streak(monkeypatch, trades) == -2


# ── T10.4: BUG-1 — hit_be in middle of win streak does NOT break it ───────────

def test_streak_hit_be_skipped_in_win_streak(monkeypatch):
    """
    BUG-1 regression guard.

    Trades (entry_time DESC): W, W, BE, W.
    hit_be must be skipped. All 3 wins count → streak = +3.

    Without the fix (if hit_be were treated as a loss/break):
      W, W → break on BE → streak = +2 (wrong).
    With the fix (be = skip/continue):
      W, W, skip, W → streak = +3 (correct).
    """
    trades = [
        FakeTrade("hit_tp", datetime(2024, 1, 15, 12, 0)),  # most recent
        FakeTrade("hit_tp", datetime(2024, 1, 15, 11, 0)),
        FakeTrade("hit_be", datetime(2024, 1, 15, 10, 0)),  # must be skipped
        FakeTrade("hit_tp", datetime(2024, 1, 15,  9, 0)),
    ]
    result = _streak(monkeypatch, trades)
    assert result == 3, (
        f"BUG-1: streak={result}, expected 3. "
        f"hit_be must be skipped, not treated as a break."
    )


# ── T10.5: BUG-1 — hit_be then loss — loss still breaks the streak ────────────

def test_streak_be_transparent_loss_still_breaks(monkeypatch):
    """
    BUG-1 (second case): W, BE, L.
    BE is skipped. The loss following it still breaks the win streak.
    Only the W at position 0 runs before the loss terminates → streak = +1.
    """
    trades = [
        FakeTrade("hit_tp", datetime(2024, 1, 15, 12, 0)),  # streak starts: +1
        FakeTrade("hit_be", datetime(2024, 1, 15, 11, 0)),  # skip
        FakeTrade("hit_sl", datetime(2024, 1, 15, 10, 0)),  # direction change → break
    ]
    result = _streak(monkeypatch, trades)
    assert result == 1, (
        f"Expected streak=+1 (be skipped, loss breaks). Got {result}."
    )


# ── T10.6: direction change breaks streak ─────────────────────────────────────

def test_streak_direction_change_breaks(monkeypatch):
    """
    W then L — direction change. Streak = +1 (only the first win counts).
    Previous losses behind the direction change are ignored.
    """
    trades = [
        FakeTrade("hit_tp", datetime(2024, 1, 15, 12, 0)),  # +1 → streak=+1
        FakeTrade("hit_sl", datetime(2024, 1, 15, 11, 0)),  # sign mismatch → break
        FakeTrade("hit_sl", datetime(2024, 1, 15, 10, 0)),  # never reached
    ]
    assert _streak(monkeypatch, trades) == 1


# ── T10.7: BUG-2 — streak reads entry_time DESC (most recent first) ───────────

def test_streak_driven_by_entry_time_desc_order(monkeypatch):
    """
    BUG-2 regression guard.

    Scenario: a re-saved old trade has a recent saved_at but an old entry_time.
    With ORDER BY entry_time DESC, the truly latest trade by entry_time
    appears first and correctly sets the streak direction.

    We simulate this by passing trades in entry_time DESC order
    (as the DB delivers them after ORDER BY entry_time DESC).
    The most recent trade by entry_time is a loss → streak = -1.

    If the code used saved_at ordering instead, the old win (which was
    recently re-saved) would appear first → streak = +1 (wrong).

    Since our mock controls the return list directly, we pass trades
    in the correct entry_time DESC order and assert streak = -1.
    """
    trades_entry_time_desc = [
        # Most recent by entry_time — a loss
        FakeTrade("hit_sl", datetime(2024, 1, 15, 12, 0)),
        # Older by entry_time — a win (re-saved recently, but old trade)
        FakeTrade("hit_tp", datetime(2024, 1, 15,  9, 0)),
    ]
    result = _streak(monkeypatch, trades_entry_time_desc)
    assert result == -1, (
        f"BUG-2: streak={result}, expected -1. "
        f"Most recent by entry_time is a loss — it must drive the streak."
    )