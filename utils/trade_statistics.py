"""
utils/trade_statistics.py
--------------------------
Pure computation layer — no Flask imports, no DB access.
Accepts plain trade dicts (from Trade.to_dict()) and returns result dicts.

FIELD SEMANTICS:
  pnl_r              — authoritative P&L: +tp_rr_target / -1.0 / 0.0 / None
  outcome_at_user_tp — 'hit_tp' / 'hit_sl' / 'hit_be' / 'open' / 'none'
  mfe_r              — trade walk peak MFE (frozen at trade close)
  mfe_at_Xh_r        — peak MFE from entry up to checkpoint (UNTP walk)
  mae_at_Xh_r        — peak MAE from entry up to checkpoint (UNTP walk)
  alive_at_Xh        — True = UNTP walk still running at checkpoint
  breakeven_triggered— True = BE activated during trade walk
  price_path_captured— False = exclude from ALL statistics

TP MODES:
  original_tp  — win=hit_tp; loss=hit_sl/hit_be; time limit disabled
  fixed_tp     — win=mfe_r>=target (trade walk peak); time limit disabled

UNTP MODES:
  fixed_untp   — win=mfe_at_Xh_r>=target (UNTP peak, frozen at stop);
                 loss=mfe_at_Xh_r<target; inconclusive=no data;
                 time limit REQUIRED; returns result_type='overview'
  untp_overview— 3-bucket (Open/SL/BE); no target; pre-split groups for
                 client-side BE toggle; time limit REQUIRED

UNTP BUCKET RULES (permanent — DECISION-12):
  Open = alive_at_Xh = True                             → PnL = mfe_at_Xh_r (floating)
  SL   = alive_at_Xh = False AND be_triggered = False   → PnL = -1.0R
  BE   = alive_at_Xh = False AND be_triggered = True    → PnL =  0.0R
  Every price_path_captured=True trade lands in exactly one bucket. No inconclusive.

original_tp win-rate rule (R7):
  hit_be = loss in original_tp statistics context (different from streak context).
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# TIME LIMIT → SNAPSHOT COLUMN MAPPING
# ═══════════════════════════════════════════════════════════════

_TIME_LIMIT_MAP: dict[Optional[float], tuple[Optional[str], Optional[str]]] = {
    None:  (None,              None),
    0.5:   ('mfe_at_30min_r',  'alive_at_30min'),
    1.0:   ('mfe_at_1h_r',     'alive_at_1h'),
    2.0:   ('mfe_at_2h_r',     'alive_at_2h'),
    4.0:   ('mfe_at_4h_r',     'alive_at_4h'),
    8.0:   ('mfe_at_8h_r',     'alive_at_8h'),
    12.0:  ('mfe_at_12h_r',    'alive_at_12h'),
    24.0:  ('mfe_at_24h_r',    'alive_at_24h'),
    48.0:  ('mfe_at_48h_r',    'alive_at_48h'),
    72.0:  ('mfe_at_72h_r',    'alive_at_72h'),
    120.0: ('mfe_at_120h_r',   'alive_at_120h'),
    168.0: ('mfe_at_168h_r',   'alive_at_168h'),
    240.0: ('mfe_at_240h_r',   'alive_at_240h'),
    336.0: ('mfe_at_336h_r',   'alive_at_336h'),
    504.0: ('mfe_at_504h_r',   'alive_at_504h'),
}

_MAE_LIMIT_MAP: dict[Optional[float], Optional[str]] = {
    None:  None,
    0.5:   'mae_at_30min_r',
    1.0:   'mae_at_1h_r',
    2.0:   'mae_at_2h_r',
    4.0:   'mae_at_4h_r',
    8.0:   'mae_at_8h_r',
    12.0:  'mae_at_12h_r',
    24.0:  'mae_at_24h_r',
    48.0:  'mae_at_48h_r',
    72.0:  'mae_at_72h_r',
    120.0: 'mae_at_120h_r',
    168.0: 'mae_at_168h_r',
    240.0: 'mae_at_240h_r',
    336.0: 'mae_at_336h_r',
    504.0: 'mae_at_504h_r',
}

TIME_LIMIT_LABELS: dict[Optional[float], str] = {
    None:  'No limit',
    0.5:   '30 min',
    1.0:   '1 hour',
    2.0:   '2 hours',
    4.0:   '4 hours',
    8.0:   '8 hours',
    12.0:  '12 hours',
    24.0:  '1 day',
    48.0:  '2 days',
    72.0:  '3 days',
    120.0: '5 days',
    168.0: '1 week',
    240.0: '10 days',
    336.0: '14 days',
    504.0: '21 days',
}

VALID_TP_MODES = frozenset({'original_tp', 'fixed_tp', 'fixed_untp', 'untp_overview'})
VALID_UNITS    = frozenset({'R', 'pips'})


# ── Helpers ────────────────────────────────────────────────────

def _get_snapshot_cols(time_limit_hours: Optional[float]) -> tuple[Optional[str], Optional[str]]:
    if time_limit_hours is None:
        return None, None
    if time_limit_hours in _TIME_LIMIT_MAP:
        return _TIME_LIMIT_MAP[time_limit_hours]
    valid = [k for k in _TIME_LIMIT_MAP if k is not None]
    nearest = min(valid, key=lambda k: abs(k - time_limit_hours))
    logger.warning("time_limit_hours=%.1f snapping to %.1f", time_limit_hours, nearest)
    return _TIME_LIMIT_MAP[nearest]


def _get_mae_col(time_limit_hours: Optional[float]) -> Optional[str]:
    if time_limit_hours is None:
        return None
    if time_limit_hours in _MAE_LIMIT_MAP:
        return _MAE_LIMIT_MAP[time_limit_hours]
    valid = [k for k in _MAE_LIMIT_MAP if k is not None]
    nearest = min(valid, key=lambda k: abs(k - time_limit_hours))
    return _MAE_LIMIT_MAP[nearest]


def _rr_target_for_trade(trade: dict, tp_value: float, unit: str) -> Optional[float]:
    """Convert tp_value to R. Returns None on zero/missing SL distance."""
    if unit == 'R':
        return tp_value
    sl_pips = trade.get('sl_distance_pips')
    if not sl_pips or sl_pips <= 0:
        return None
    return tp_value / sl_pips


def _entry_label(trade: dict) -> str:
    label = trade.get('entry_time', '') or ''
    if hasattr(label, 'strftime'):
        return label.strftime('%Y-%m-%d')
    if isinstance(label, str) and len(label) >= 10:
        return label[:10]
    return str(label)


# ═══════════════════════════════════════════════════════════════
# WIN/LOSS RESOLVER — original_tp and fixed_tp only
# ═══════════════════════════════════════════════════════════════

def resolve_win_loss(
    trade: dict,
    tp_mode: str,
    tp_value: Optional[float],
    time_limit_hours: Optional[float],
    unit: str = 'R',
) -> str:
    """
    Classify trade as 'win' | 'loss' | 'inconclusive'.
    For original_tp and fixed_tp only.
    UNTP modes use compute_untp_stats().

    PRECONDITION: trade['price_path_captured'] is True.
    """
    outcome = trade.get('outcome_at_user_tp')

    if tp_mode == 'original_tp':
        if outcome == 'hit_tp':
            return 'win'
        elif outcome in ('hit_sl', 'hit_be'):
            return 'loss'    # R7: hit_be = loss in statistics context
        else:
            return 'inconclusive'

    if tp_mode == 'fixed_tp':
        if tp_value is None or tp_value <= 0:
            return 'inconclusive'
        rr_target = _rr_target_for_trade(trade, tp_value, unit)
        if rr_target is None:
            return 'inconclusive'
        mfe_val = trade.get('mfe_r')
        if mfe_val is None:
            return 'inconclusive'
        if mfe_val >= rr_target:
            return 'win'
        elif outcome in ('hit_sl', 'hit_be'):
            return 'loss'
        else:
            return 'inconclusive'

    return 'inconclusive'


# ═══════════════════════════════════════════════════════════════
# EFFECTIVE PNL — original_tp and fixed_tp
# ═══════════════════════════════════════════════════════════════

def _effective_pnl(
    trade: dict,
    tp_mode: str,
    tp_value: Optional[float],
    result: str,
    unit: str = 'R',
) -> float:
    if result == 'win':
        if tp_mode == 'original_tp':
            return float(trade.get('pnl_r') or 0.0)
        else:
            rr = _rr_target_for_trade(trade, tp_value or 0.0, unit)
            return float(rr or 0.0)
    else:  # loss
        if tp_mode == 'original_tp':
            v = trade.get('pnl_r')
            return float(v) if v is not None else -1.0   # BUG-6: 0.0 (hit_be) must not fall to -1.0
        else:
            return -1.0


# ═══════════════════════════════════════════════════════════════
# MODULE 1 OVERVIEW — original_tp and fixed_tp
# ═══════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
# FIXED UNTP OVERVIEW
# ═══════════════════════════════════════════════════════════════

def compute_fixed_untp_overview(
    trades: list[dict],
    tp_value: float,
    time_limit_hours: float,
    unit: str = 'R',
) -> dict:
    """
    Fixed UNTP: did the UNTP walk reach tp_value at any point before it stopped?

    mfe_at_Xh_r = peak MFE the UNTP walk achieved up to checkpoint X,
    frozen at UNTP-stop value if walk ended (SL/BE) before X.
    So this answers: "did it ever touch the target?" — alive_at_Xh is irrelevant.

    Win          = mfe_at_Xh_r >= rr_target   (reached target before stopping)
    Loss         = mfe_at_Xh_r <  rr_target   (never reached it)
    Inconclusive = mfe_at_Xh_r is None        (no UNTP data)

    Denominator = wins + losses (inconclusive excluded).
    Returns result_type='overview' — renderOverview() handles it unchanged.
    """
    excluded = [t for t in trades if not t.get('price_path_captured')]
    good     = [t for t in trades if t.get('price_path_captured')]

    mfe_col, _  = _get_snapshot_cols(time_limit_hours)   # alive_col not needed
    mae_col     = _get_mae_col(time_limit_hours)

    total_trades   = len(trades)
    excluded_count = len(excluded)

    # (trade, result, pnl_or_None)
    classified: list[tuple[dict, str, Optional[float]]] = []
    mfe_vals:   list[float] = []
    mae_vals:   list[float] = []
    inconclusive_cnt = 0

    for t in good:
        mfe_val   = t.get(mfe_col) if mfe_col else None
        rr_target = _rr_target_for_trade(t, tp_value, unit)

        if mfe_val is None or rr_target is None:
            inconclusive_cnt += 1
            classified.append((t, 'inconclusive', None))
            continue

        mfe_vals.append(float(mfe_val))
        mae_v = t.get(mae_col) if mae_col else None
        if mae_v is not None:
            mae_vals.append(float(mae_v))

        if float(mfe_val) >= rr_target:
            classified.append((t, 'win', rr_target))
        else:
            classified.append((t, 'loss', -1.0))

    wins   = sum(1 for (_, r, _) in classified if r == 'win')
    losses = sum(1 for (_, r, _) in classified if r == 'loss')
    evaluated = wins + losses

    win_pnls  = [pnl for (_, r, pnl) in classified if r == 'win']
    loss_pnls = [pnl for (_, r, pnl) in classified if r == 'loss']
    net_rr    = round(sum(win_pnls) + sum(loss_pnls), 4)

    win_rate   = round(wins   / evaluated * 100.0, 1) if evaluated > 0 else 0.0
    expectancy = round(net_rr / evaluated,          4) if evaluated > 0 else 0.0
    avg_mfe_r  = round(sum(mfe_vals)  / len(mfe_vals),  3) if mfe_vals  else 0.0
    avg_mae_r  = round(sum(mae_vals)  / len(mae_vals),  3) if mae_vals  else 0.0
    avg_win_r  = round(sum(win_pnls)  / len(win_pnls),  3) if win_pnls  else 0.0
    avg_loss_r = round(sum(loss_pnls) / len(loss_pnls), 3) if loss_pnls else 0.0

    # Equity curve — evaluated trades only, chronological
    equity_curve:   list[list] = []
    drawdown_curve: list[list] = []
    running = 0.0
    for (t, result, pnl) in classified:
        if result == 'inconclusive':
            continue
        running += pnl  # type: ignore[operator]
        equity_curve.append([_entry_label(t), round(running, 4)])

    peak = max_dd = 0.0
    for _, cum in equity_curve:
        if cum > peak:
            peak = cum
        dd = round(peak - cum, 4)
        if dd > max_dd:
            max_dd = dd
        drawdown_curve.append([_entry_label(t), -dd])  # label reused — fix below

    # Rebuild drawdown with correct labels
    drawdown_curve = []
    peak = 0.0
    for label, cum in equity_curve:
        if cum > peak:
            peak = cum
        dd = round(peak - cum, 4)
        drawdown_curve.append([label, -dd])

    # Streaks (inconclusive = skip, doesn't reset)
    max_win_streak = max_loss_streak = 0
    cur_win = cur_loss = 0
    for (_, result, _) in classified:
        if result == 'win':
            cur_win += 1; cur_loss = 0
            max_win_streak = max(max_win_streak, cur_win)
        elif result == 'loss':
            cur_loss += 1; cur_win = 0
            max_loss_streak = max(max_loss_streak, cur_loss)
        # inconclusive: skip

    return {
        'result_type':        'overview',
        'tp_mode':            'fixed_untp',
        'tp_value':           tp_value,
        'unit':               unit,
        'time_limit_label':   TIME_LIMIT_LABELS.get(time_limit_hours, 'No limit'),
        'total_trades':       total_trades,
        'excluded_count':     excluded_count,
        'evaluated_count':    evaluated,
        'wins':               wins,
        'losses':             losses,
        'inconclusive_count': inconclusive_cnt,
        'win_rate':           win_rate,
        'net_rr':             net_rr,
        'expectancy':         expectancy,
        'avg_mfe_r':          avg_mfe_r,
        'avg_mae_r':          avg_mae_r,
        'avg_win_r':          avg_win_r,
        'avg_loss_r':         avg_loss_r,
        'max_drawdown':       round(max_dd, 3),
        'max_win_streak':     max_win_streak,
        'max_loss_streak':    max_loss_streak,
        'equity_curve':       equity_curve,
        'drawdown_curve':     drawdown_curve,
        'outcome_breakdown':  {},   # not applicable — original_tp field only
        'sample_warning':     evaluated < 20,
    }

def compute_overview(
    trades: list[dict],
    tp_mode: str,
    tp_value: Optional[float],
    time_limit_hours: Optional[float],
    unit: str = 'R',
) -> dict:
    """
    Compute Module 1 overview for original_tp and fixed_tp modes.
    time_limit_hours ignored (caller enforces None).
    """
    excluded = [t for t in trades if not t.get('price_path_captured')]
    good     = [t for t in trades if t.get('price_path_captured')]

    excluded_count = len(excluded)
    total_trades   = len(trades)

    results: list[str] = [
        resolve_win_loss(t, tp_mode, tp_value, None, unit) for t in good
    ]

    wins_list   = [t for t, r in zip(good, results) if r == 'win']
    losses_list = [t for t, r in zip(good, results) if r == 'loss']
    incon_list  = [t for t, r in zip(good, results) if r == 'inconclusive']

    wins             = len(wins_list)
    losses           = len(losses_list)
    inconclusive_cnt = len(incon_list)
    evaluated        = wins + losses

    win_rate = (wins / evaluated * 100.0) if evaluated > 0 else 0.0

    # Equity curve
    equity_pairs: list[tuple[str, float]] = []
    for t, r in zip(good, results):
        if r in ('win', 'loss'):
            equity_pairs.append((_entry_label(t), _effective_pnl(t, tp_mode, tp_value, r, unit)))

    equity_curve: list[list] = []
    running = 0.0
    for label, pnl in equity_pairs:
        running += pnl
        equity_curve.append([label, round(running, 4)])

    net_rr     = round(running, 4)
    expectancy = round(net_rr / evaluated, 4) if evaluated > 0 else 0.0

    # Drawdown
    drawdown_curve: list[list] = []
    peak = max_dd = 0.0
    for label, cum in equity_curve:
        if cum > peak:
            peak = cum
        dd = round(peak - cum, 4)
        if dd > max_dd:
            max_dd = dd
        drawdown_curve.append([label, -dd])

    # Avg MFE / MAE (trade walk fields)
    mfe_vals = [
        t.get('mfe_r') for t, r in zip(good, results)
        if r in ('win', 'loss') and t.get('mfe_r') is not None
    ]
    mae_vals = [
        t.get('mae_r') for t, r in zip(good, results)
        if r in ('win', 'loss') and t.get('mae_r') is not None
    ]
    avg_mfe_r = round(sum(mfe_vals) / len(mfe_vals), 3) if mfe_vals else 0.0
    avg_mae_r = round(sum(mae_vals) / len(mae_vals), 3) if mae_vals else 0.0

    win_pnls  = [_effective_pnl(t, tp_mode, tp_value, 'win',  unit) for t in wins_list]
    loss_pnls = [_effective_pnl(t, tp_mode, tp_value, 'loss', unit) for t in losses_list]
    avg_win_r  = round(sum(win_pnls)  / len(win_pnls),  3) if win_pnls  else 0.0
    avg_loss_r = round(sum(loss_pnls) / len(loss_pnls), 3) if loss_pnls else 0.0

    # Streaks (inconclusive = skip, doesn't reset streaks)
    max_win_streak = max_loss_streak = 0
    cur_win = cur_loss = 0
    for r in results:
        if r == 'win':
            cur_win += 1; cur_loss = 0
            max_win_streak = max(max_win_streak, cur_win)
        elif r == 'loss':
            cur_loss += 1; cur_win = 0
            max_loss_streak = max(max_loss_streak, cur_loss)

    # Outcome breakdown
    outcome_breakdown: dict[str, int] = {
        'hit_tp': 0, 'hit_sl': 0, 'hit_be': 0, 'open': 0, 'none': 0,
    }
    for t in good:
        oc = t.get('outcome_at_user_tp') or 'none'
        if oc in outcome_breakdown:
            outcome_breakdown[oc] += 1

    return {
        'result_type':        'overview',
        'tp_mode':            tp_mode,
        'tp_value':           tp_value,
        'unit':               unit,
        'total_trades':       total_trades,
        'excluded_count':     excluded_count,
        'evaluated_count':    evaluated,
        'wins':               wins,
        'losses':             losses,
        'inconclusive_count': inconclusive_cnt,
        'win_rate':           round(win_rate, 1),
        'net_rr':             net_rr,
        'expectancy':         expectancy,
        'avg_mfe_r':          avg_mfe_r,
        'avg_mae_r':          avg_mae_r,
        'avg_win_r':          avg_win_r,
        'avg_loss_r':         avg_loss_r,
        'max_drawdown':       round(max_dd, 3),
        'max_win_streak':     max_win_streak,
        'max_loss_streak':    max_loss_streak,
        'equity_curve':       equity_curve,
        'drawdown_curve':     drawdown_curve,
        'outcome_breakdown':  outcome_breakdown,
        'sample_warning':     evaluated < 20,
        'time_limit_label':   TIME_LIMIT_LABELS.get(None, 'No limit'),
    }


# ═══════════════════════════════════════════════════════════════
# UNTP GROUP HELPER
# ═══════════════════════════════════════════════════════════════

def _compute_untp_group(
    subset: list[dict],
    mfe_col: Optional[str],
    alive_col: Optional[str],
    mae_col: Optional[str],
) -> dict:
    """
    Compute UNTP bucket stats for one subset of trades.
    Called three times per request: all, be_active, no_be.

    Bucket rules (DECISION-12):
      Open = alive=True                      → PnL = mfe_at_Xh_r
      SL   = alive=False, be_triggered=False → PnL = -1.0
      BE   = alive=False, be_triggered=True  → PnL = 0.0

    Streaks (mirrors R5 rule):
      Open streak: consecutive Open outcomes; BE = skip (doesn't break Open streak)
      SL streak:   consecutive SL outcomes;  BE = skip (doesn't break SL streak)
    """
    open_list: list[dict] = []
    sl_list:   list[dict] = []
    be_list:   list[dict] = []

    for t in subset:
        alive = t.get(alive_col) if alive_col else None
        if alive:
            open_list.append(t)
        elif t.get('breakeven_triggered'):
            be_list.append(t)
        else:
            sl_list.append(t)

    open_count = len(open_list)
    sl_count   = len(sl_list)
    be_count   = len(be_list)
    evaluated  = open_count + sl_count + be_count

    open_rate = round(open_count / evaluated * 100.0, 1) if evaluated > 0 else 0.0

    # Equity curve — all trades chronological; Open→mfe, SL→-1, BE→0
    equity_curve: list[list] = []
    running = 0.0
    for t in subset:
        alive = t.get(alive_col) if alive_col else None
        if alive:
            v = t.get(mfe_col) if mfe_col else None
            pnl = float(v) if v is not None else 0.0
        elif t.get('breakeven_triggered'):
            pnl = 0.0
        else:
            pnl = -1.0
        running += pnl
        equity_curve.append([_entry_label(t), round(running, 4)])

    net_r      = round(running, 4)
    expectancy = round(net_r / evaluated, 4) if evaluated > 0 else 0.0

    # Drawdown
    drawdown_curve: list[list] = []
    peak = max_dd = 0.0
    for label, cum in equity_curve:
        if cum > peak:
            peak = cum
        dd = round(peak - cum, 4)
        if dd > max_dd:
            max_dd = dd
        drawdown_curve.append([label, -dd])

    # Avg MFE / MAE at window for Open trades only
    open_mfe_vals = [
        t.get(mfe_col) for t in open_list
        if mfe_col and t.get(mfe_col) is not None
    ]
    open_mae_vals = [
        t.get(mae_col) for t in open_list
        if mae_col and t.get(mae_col) is not None
    ]
    avg_open_mfe_r = round(sum(open_mfe_vals) / len(open_mfe_vals), 3) if open_mfe_vals else 0.0
    avg_open_mae_r = round(sum(open_mae_vals) / len(open_mae_vals), 3) if open_mae_vals else 0.0

    # Streaks — BE = skip (mirrors R5 from mfe_calculator._compute_streak)
    max_open_streak = max_sl_streak = 0
    cur_open = cur_sl = 0
    for t in subset:
        alive    = t.get(alive_col) if alive_col else None
        be_trig  = t.get('breakeven_triggered')
        if alive:
            cur_open += 1
            cur_sl    = 0
            max_open_streak = max(max_open_streak, cur_open)
        elif not be_trig:
            # SL
            cur_sl  += 1
            cur_open = 0
            max_sl_streak = max(max_sl_streak, cur_sl)
        # BE: skip — neither streak counter touched

    return {
        'total':            evaluated,
        'open_count':       open_count,
        'sl_count':         sl_count,
        'be_count':         be_count,
        'open_rate':        open_rate,
        'net_r':            net_r,
        'expectancy':       expectancy,
        'avg_open_mfe_r':   avg_open_mfe_r,
        'avg_open_mae_r':   avg_open_mae_r,
        'max_drawdown':     round(max_dd, 3),
        'max_open_streak':  max_open_streak,
        'max_sl_streak':    max_sl_streak,
        'equity_curve':     equity_curve,
        'drawdown_curve':   drawdown_curve,
        'sample_warning':   evaluated < 20,
    }


# ═══════════════════════════════════════════════════════════════
# UNTP STATS — fixed_untp and untp_overview
# ═══════════════════════════════════════════════════════════════

def compute_untp_stats(
    trades: list[dict],
    time_limit_hours: float,
    tp_mode: str = 'untp_overview',
    tp_value: Optional[float] = None,
    unit: str = 'R',
) -> dict:
    """
    Compute UNTP statistics for fixed_untp and untp_overview.

    Returns three pre-computed groups so the BE toggle is purely
    client-side — no server round-trip when the user switches the toggle.

      stats_all       — all price_path_captured=True trades
      stats_be_active — trades where breakeven_triggered=True
      stats_no_be     — trades where breakeven_triggered=False

    Parameters:
      trades           — trade dicts ordered by entry_time ASC
      time_limit_hours — UNTP checkpoint to evaluate at (required)
      tp_mode          — 'fixed_untp' | 'untp_overview'
      tp_value         — reference target for fixed_untp meta; None for overview
      unit             — 'R' | 'pips' (meta display for fixed_untp)
    """
    excluded = [t for t in trades if not t.get('price_path_captured')]
    good     = [t for t in trades if t.get('price_path_captured')]

    mfe_col, alive_col = _get_snapshot_cols(time_limit_hours)
    mae_col            = _get_mae_col(time_limit_hours)

    be_active = [t for t in good if t.get('breakeven_triggered')]
    no_be     = [t for t in good if not t.get('breakeven_triggered')]

    return {
        'result_type':      'untp_stats',
        'tp_mode':          tp_mode,
        'tp_value':         tp_value,
        'unit':             unit,
        'time_limit_label': TIME_LIMIT_LABELS.get(time_limit_hours, 'No limit'),
        'total_trades':     len(trades),
        'excluded_count':   len(excluded),
        'stats_all':        _compute_untp_group(good,      mfe_col, alive_col, mae_col),
        'stats_be_active':  _compute_untp_group(be_active, mfe_col, alive_col, mae_col),
        'stats_no_be':      _compute_untp_group(no_be,     mfe_col, alive_col, mae_col),
    }

# ═══════════════════════════════════════════════════════════════
# MODULE 7 — PNL REPORT
# ═══════════════════════════════════════════════════════════════

def _parse_entry_dt(trade: dict) -> Optional[datetime]:
    """Parse entry_time to datetime. Handles datetime objects and YYYY-MM-DD strings."""
    entry = trade.get('entry_time')
    if entry is None:
        return None
    if hasattr(entry, 'isocalendar'):
        return entry
    if isinstance(entry, str) and len(entry) >= 10:
        try:
            return datetime.strptime(entry[:10], '%Y-%m-%d')
        except ValueError:
            return None
    return None


def compute_pnl_report(trades: list[dict]) -> dict:
    """
    Module 7 — PnL Report.

    Uses pnl_r only (R2 — authoritative). Never touches TP mode, unit, or
    time limit — those are evaluation-mode concerns.

    trades must be ordered by entry_time ASC (guaranteed by _load_trades).

    Evaluated = price_path_captured=True AND pnl_r is not None
      hit_tp  → pnl_r = +tp_rr_target  (counted, positive step)
      hit_sl  → pnl_r = -1.0           (counted, negative step)
      hit_be  → pnl_r = 0.0            (counted, flat step — PR3)
      open    → pnl_r = None           (excluded — PR2)
      none    → pnl_r = None           (excluded — PR2)

    Streak rules (R5/R6 — same as channel_streak_at_save):
      Win  = hit_tp only
      Loss = hit_sl only
      Skip = hit_be / open / none  (do NOT break streaks)
    """
    excluded = [t for t in trades if not t.get('price_path_captured')]
    good     = [t for t in trades if t.get('price_path_captured')]

    excluded_count = len(excluded)
    total_trades   = len(trades)

    # Evaluated trades — pnl_r must be non-None (excludes open/none)
    evaluated = [t for t in good if t.get('pnl_r') is not None]
    evaluated_count = len(evaluated)

    # ── Equity curve ─────────────────────────────────────────
    equity_curve: list[list] = []
    running = 0.0
    for t in evaluated:
        running += float(t['pnl_r'])
        equity_curve.append([_entry_label(t), round(running, 4)])
    net_rr = round(running, 4)

    # ── Weekly + monthly totals ───────────────────────────────
    # PR9: use entry_time (not saved_at)
    weekly_map:  dict[str, dict] = {}
    monthly_map: dict[str, dict] = {}

    for t in evaluated:
        dt = _parse_entry_dt(t)
        if dt is None:
            continue
        iso       = dt.isocalendar()
        week_key  = f'{iso[0]}-W{iso[1]:02d}'
        month_key = dt.strftime('%Y-%m')
        pnl       = float(t['pnl_r'])

        if week_key not in weekly_map:
            weekly_map[week_key] = {'net_rr': 0.0, 'count': 0, '_dt': dt}
        weekly_map[week_key]['net_rr'] += pnl
        weekly_map[week_key]['count']  += 1

        if month_key not in monthly_map:
            monthly_map[month_key] = {'net_rr': 0.0, 'count': 0}
        monthly_map[month_key]['net_rr'] += pnl
        monthly_map[month_key]['count']  += 1

    # PR8: fill zero-trade weeks between first and last evaluated trade
    if evaluated:
        first_dt = next((_parse_entry_dt(t) for t in evaluated if _parse_entry_dt(t)), None)
        last_dt  = next((_parse_entry_dt(t) for t in reversed(evaluated) if _parse_entry_dt(t)), None)
        if first_dt and last_dt:
            cursor = first_dt - timedelta(days=first_dt.weekday())  # Monday of first week
            last_monday = last_dt - timedelta(days=last_dt.weekday())
            while cursor <= last_monday:
                iso      = cursor.isocalendar()
                week_key = f'{iso[0]}-W{iso[1]:02d}'
                if week_key not in weekly_map:
                    weekly_map[week_key] = {'net_rr': 0.0, 'count': 0, '_dt': cursor}
                cursor += timedelta(weeks=1)

    weekly_totals = [
        {'week': k, 'net_rr': round(v['net_rr'], 3), 'count': v['count']}
        for k, v in sorted(weekly_map.items())
    ]
    monthly_totals = [
        {'month': k, 'net_rr': round(v['net_rr'], 3), 'count': v['count']}
        for k, v in sorted(monthly_map.items())
    ]

    # ── Per-symbol ────────────────────────────────────────────
    symbol_map: dict[str, dict] = {}
    for t in evaluated:
        sym = t.get('symbol') or 'Unknown'
        if sym not in symbol_map:
            symbol_map[sym] = {'net_rr': 0.0, 'count': 0}
        symbol_map[sym]['net_rr'] += float(t['pnl_r'])
        symbol_map[sym]['count']  += 1

    # PR12: sorted by net_rr descending. PR13: zero-count entries excluded.
    by_symbol = [
        {'symbol': sym, 'net_rr': round(v['net_rr'], 3), 'count': v['count']}
        for sym, v in symbol_map.items()
        if v['count'] > 0
    ]
    by_symbol.sort(key=lambda r: r['net_rr'], reverse=True)

    # ── Streaks (R5/R6) ───────────────────────────────────────
    # Iterate good (price_path_captured=True) in entry_time order.
    # hit_be / open / none = skip (counters NOT reset).
    max_win_streak = max_loss_streak = 0
    cur_win = cur_loss = 0
    for t in good:
        outcome = t.get('outcome_at_user_tp')
        if outcome == 'hit_tp':
            cur_win += 1; cur_loss = 0
            max_win_streak = max(max_win_streak, cur_win)
        elif outcome == 'hit_sl':
            cur_loss += 1; cur_win = 0
            max_loss_streak = max(max_loss_streak, cur_loss)
        # hit_be / open / none: skip — neither counter touched

    return {
        'result_type':    'pnl_report',
        'total_trades':   total_trades,
        'excluded_count': excluded_count,
        'evaluated_count': evaluated_count,
        'net_rr':         net_rr,
        'equity_curve':   equity_curve,
        'weekly_totals':  weekly_totals,
        'monthly_totals': monthly_totals,
        'by_symbol':      by_symbol,
        'max_win_streak': max_win_streak,
        'max_loss_streak': max_loss_streak,
        'sample_warning': evaluated_count < 20,
    }

# ── Module 2 dimension label maps ──────────────────────────────    
_DOW_LABELS    = {0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri'}
_DOW_ORDER     = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
_TYPE_LABELS   = {
    'buy': 'Buy', 'sell': 'Sell',
    'limit_buy': 'Limit Buy', 'limit_sell': 'Limit Sell',
    'stop_buy': 'Stop Buy', 'stop_sell': 'Stop Sell',
}
_SESSION_LABELS = {
    'asian': 'Asian', 'london': 'London',
    'overlap': 'Overlap', 'new_york': 'New York',
    'off_hours': 'Off Hours',
}


def _classify_for_hitrate(
    trade: dict,
    tp_mode: str,
    tp_value: Optional[float],
    unit: str,
    mfe_col: Optional[str],
    alive_col: Optional[str],
) -> tuple[str, float]:
    """
    Classify one trade for hit rate bucketing.
    Returns (bucket, pnl).

    Win/loss modes buckets: 'win' | 'loss' | 'inconclusive'
    untp_overview buckets:  'open' | 'sl'  | 'be'
    """
    if tp_mode == 'untp_overview':
        alive = trade.get(alive_col) if alive_col else None
        if alive:
            mfe_v = trade.get(mfe_col) if mfe_col else None
            return 'open', float(mfe_v) if mfe_v is not None else 0.0
        elif trade.get('breakeven_triggered'):
            return 'be', 0.0
        else:
            return 'sl', -1.0

    if tp_mode == 'fixed_untp':
        # BUG-16 / DECISION-15: alive_at_Xh is irrelevant.
        # Win = mfe_at_Xh_r >= target. Loss = mfe_at_Xh_r < target.
        # Inconclusive = no mfe data.
        mfe_val   = trade.get(mfe_col) if mfe_col else None
        rr_target = _rr_target_for_trade(trade, tp_value or 0.0, unit)
        if mfe_val is None or rr_target is None:
            return 'inconclusive', 0.0
        if float(mfe_val) >= rr_target:
            return 'win', float(rr_target)
        return 'loss', -1.0

    # original_tp / fixed_tp — delegate to existing resolver
    result = resolve_win_loss(trade, tp_mode, tp_value, None, unit)
    if result == 'win':
        return 'win', _effective_pnl(trade, tp_mode, tp_value, 'win', unit)
    if result == 'loss':
        return 'loss', _effective_pnl(trade, tp_mode, tp_value, 'loss', unit)
    return 'inconclusive', 0.0


def _build_hitrate_rows(
    groups: dict[str, list[dict]],
    tp_mode: str,
    tp_value: Optional[float],
    unit: str,
    mfe_col: Optional[str],
    alive_col: Optional[str],
    sort_by_label_order: Optional[list[str]] = None,
) -> list[dict]:
    """
    Build one list of hit-rate rows from a {label: [trades]} grouping.

    sort_by_label_order: if provided, rows are sorted by their position in
    this list (e.g. Mon→Fri for day_of_week). Unknown labels go last.
    Otherwise rows are sorted by evaluated-trade count descending.
    """
    rows = []
    for label, trades in groups.items():
        wins = losses = inconclusive = open_c = sl_c = be_c = 0
        net = 0.0
        for t in trades:
            if not t.get('price_path_captured'):
                continue
            bucket, pnl = _classify_for_hitrate(
                t, tp_mode, tp_value, unit, mfe_col, alive_col
            )
            net += pnl
            if   bucket == 'win':          wins += 1
            elif bucket == 'loss':         losses += 1
            elif bucket == 'open':         open_c += 1
            elif bucket == 'sl':           sl_c += 1
            elif bucket == 'be':           be_c += 1
            else:                          inconclusive += 1  # 'inconclusive'

        if tp_mode == 'untp_overview':
            total     = open_c + sl_c + be_c
            open_rate = round(open_c / total * 100.0, 1) if total > 0 else 0.0
            rows.append({
                'label':        label,
                'total':        total,
                'wins':         0,
                'losses':       0,
                'inconclusive': 0,
                'win_rate':     None,
                'net_rr':       round(net, 3),
                'open_count':   open_c,
                'sl_count':     sl_c,
                'be_count':     be_c,
                'open_rate':    open_rate,
            })
        else:
            evaluated = wins + losses
            win_rate  = round(wins / evaluated * 100.0, 1) if evaluated > 0 else None
            rows.append({
                'label':        label,
                'total':        evaluated,
                'wins':         wins,
                'losses':       losses,
                'inconclusive': inconclusive,
                'win_rate':     win_rate,
                'net_rr':       round(net, 3),
                'open_count':   0,
                'sl_count':     0,
                'be_count':     0,
                'open_rate':    0.0,
            })

    if sort_by_label_order:
        rows.sort(
            key=lambda r: sort_by_label_order.index(r['label'])
                          if r['label'] in sort_by_label_order else 99
        )
    else:
        rows.sort(key=lambda r: r['total'], reverse=True)

    return rows


# ═══════════════════════════════════════════════════════════════
# MODULE 2 — HIT RATE
# ═══════════════════════════════════════════════════════════════

def compute_hit_rate(
    trades: list[dict],
    tp_mode: str,
    tp_value: Optional[float] = None,
    time_limit_hours: Optional[float] = None,
    unit: str = 'R',
) -> dict:
    """
    Module 2 — Hit Rate Analysis.
    Breakdown by symbol, trade_type, session, day_of_week.

    All 4 modes supported:
      original_tp / fixed_tp / fixed_untp → wins/losses/inconclusive per row
      untp_overview                        → open/sl/be counts per row

    fixed_untp semantics (BUG-16):
      win  = mfe_at_Xh_r >= target  (alive_at_Xh is IRRELEVANT)
      loss = mfe_at_Xh_r <  target
      inconclusive = mfe_at_Xh_r is None

    price_path_captured=False trades excluded per row.
    """
    excluded_count      = sum(1 for t in trades if not t.get('price_path_captured'))
    mfe_col, alive_col  = _get_snapshot_cols(time_limit_hours)

    # Build dimension groups — include all trades (excluded filtered per-row inside helper)
    by_symbol:     dict[str, list[dict]] = {}
    by_trade_type: dict[str, list[dict]] = {}
    by_session:    dict[str, list[dict]] = {}
    by_dow:        dict[str, list[dict]] = {}

    for t in trades:
        sym     = t.get('symbol') or 'Unknown'
        tt_raw  = t.get('trade_type') or 'unknown'
        sess_raw= t.get('entry_session') or 'unknown'
        dow_num = t.get('entry_day_of_week')
        tt      = _TYPE_LABELS.get(tt_raw, tt_raw)
        sess    = _SESSION_LABELS.get(sess_raw, sess_raw.title())

        by_symbol.setdefault(sym,  []).append(t)
        by_trade_type.setdefault(tt,   []).append(t)
        by_session.setdefault(sess, []).append(t)
        if dow_num in _DOW_LABELS:                          
         by_dow.setdefault(_DOW_LABELS[dow_num], []).append(t)

    common = dict(
        tp_mode=tp_mode, tp_value=tp_value, unit=unit,
        mfe_col=mfe_col, alive_col=alive_col,
    )

    return {
        'result_type':      'hitrate',
        'tp_mode':          tp_mode,
        'tp_value':         tp_value,
        'unit':             unit,
        'time_limit_label': TIME_LIMIT_LABELS.get(time_limit_hours, 'No limit'),
        'total_trades':     len(trades),
        'excluded_count':   excluded_count,
        'dimensions': {
            'symbol':      _build_hitrate_rows(by_symbol,     **common),
            'trade_type':  _build_hitrate_rows(by_trade_type, **common),
            'session':     _build_hitrate_rows(by_session,    **common),
            'day_of_week': _build_hitrate_rows(
                               by_dow, **common,
                               sort_by_label_order=_DOW_ORDER,
                           ),
        },
    }