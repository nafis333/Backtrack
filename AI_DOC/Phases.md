# PHASES — phase specs and completion criteria. Current section loaded on demand.

## PHASE STATUS SUMMARY
Phase 1  DB + Save Trade                       COMPLETE
Phase 2  Channel UI + Drawer                   COMPLETE
Phase 3  Calculator Hardening                  COMPLETE — 135/135 tests
Phase 4  Statistics Hub + Modules 1 & 2        COMPLETE
Phase 5  Module 2 (Hit Rate) + Module 7 (PnL)  COMPLETE
Phase 6  Full Simulator Suite                  NOT STARTED — prerequisite: Phase 5
Phase 7  Module 5 (Dip) + Module 6 (Strategy)  NOT STARTED — prerequisite: Phase 6
Phase 8  Polish + Bonus                        NOT STARTED — prerequisite: Phase 7
Phase 10 Claimed TP Tracking                   NOT STARTED — no prerequisite (DECISION-19)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 6 — FULL SIMULATOR SUITE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: NOT STARTED

Core purpose: mathematically find the optimal TP for any channel's signals
at candle-level precision, with or without BE simulation,
using already-loaded parquet data (zero disk I/O at query time).

Build order: walk_engine.py → M1 upgrade → M3 RR Sweep → M4 BE Comparison

─── SHARED ENGINE — utils/walk_engine.py ───────────────────────────────
New file. Used by M1, M3, M4.

walk_trade_untp(trade, data_frames, max_minutes, be_active, be_trigger_r) -> dict
  Returns: peak_mfe_r, peak_mae_r, stop_reason, stopped_at_min, path[[min,mfe,mae],...]
  Stop reasons: 'sl' | 'be' | 'time_limit' | 'open'
  be_active=True:  trigger BE at user be_trigger_r. Trade BE config NEVER read.
  be_active=False: walk to original SL only. stop_reason never 'be'.
  WalkDataError if entry not in parquet.
  Open trades walk to data end, capped at 30240 min.
  No DB writes. Uses data_frames (zero disk I/O).
  Performance: warn >100 trades, confirm >300.

─── M1 UPGRADE — fixed_untp and untp_overview ──────────────────────────
Route: POST /statistics/overview — same route, same response shape.
Server calls walk_trade_untp() twice per trade (BE on + BE off).
Returns: stats_be_on + stats_be_off (replaces old stats_all/stats_be_active/stats_no_be).

fixed_untp:    Win = peak_mfe_r >= target. Loss = peak_mfe_r < target.
untp_overview: Open = stop_reason in (time_limit, open). SL = sl. BE = be (BE-on only).

UI changes (stats_m1_overview.html):
  BE On / BE Off / Difference buttons in results area after run
  Time limit dropdown gains "No limit" option (= 30240 min cap)
  be_trigger_r input per module (separate from M3)
  Old sidebar BE toggle (All/BE Active/No BE) removed

─── M3 — RR SWEEP (stats_m3_sweep.html) ───────────────────────────────
Answers: What is the optimal TP target for this channel within my time window?

Server (one request):
  walk_trade_untp() once per trade (one BE mode per request)
  Returns per trade: trade_id, entry_time, session, path[[min, mfe, mae],...]
  Client holds path permanently — all sweep calculations client-side

R target sweep — adaptive steps:
  0.25R: 0.25 → 3.0R
  0.50R: 3.0 → 6.0R
  1.00R: 6.0 → max(peak_mfe) rounded up

Per target row:
  Target R, Trades, Wins, Win Rate, EV=(wr×target)+(lr×-1.0), Net R
  Avg MAE before target (wins: max mae up to first target hit)
  MAE:Target ratio (avg_mae_before / target)
  Median time-to-target (wins: median elapsed_min when mfe first crossed target)
  Max consec losses (entry_time order, R6 rule)
  Early exit % (wins where 75% of target hit within first 25% of time limit)
  Confidence: Red<20 / Yellow 20-49 / Green 50+
  Verdict: ★ Best EV / ◆ Best risk-adjusted = EV/(max_consec_losses+1)
  Dead zone: EV<0 greyed

Filters (client-side, instant):
  Time limit slider (any minutes 1-30240)
  Session: All/Asian/London/Overlap/New York
  BE toggle: switching triggers new server request, result cached per mode

Difference drawer: per-target win rate/EV/net R change between BE on and BE off.

─── M4 — BE COMPARISON (stats_m4_becompare.html) ──────────────────────
Answers: Does adding a breakeven stop help or hurt this channel's signals?

Server: walk_trade_untp() twice per trade (BE on + BE off).
Returns two groups at user's time limit:
  Group A (BE on): fresh re-walk with user's be_trigger_r
  Group B (BE off): fresh re-walk, SL only

Per group: open/sl/be count, avg peak MFE, avg peak MAE, net R, max consec stops.
BE count always 0 in Group B.
Difference column: Group B - Group A. Green=BE off better, Red=BE on better.
All trades included — not filtered by saved BE state.
UI: BE On / BE Off / Difference drawer pages.
Separate be_trigger_r input from M1 and M3.

─── ROUTES ─────────────────────────────────────────────────────────────
POST /statistics/overview    M1 upgraded (stats_be_on + stats_be_off)
POST /statistics/sweep       M3 RR Sweep (path per trade, one BE mode per request)
POST /statistics/becompare   M4 BE Comparison (both walks, aggregated)
POST /statistics/hitrate     M2 (Phase 5, exists)
POST /statistics/pnl         M7 (Phase 5, exists)

─── COMPLETION CRITERIA ────────────────────────────────────────────────
Walk Engine:
  ✓ data_frames pre-loaded — zero disk reads
  ✓ stop_reason correctly set for all four cases
  ✓ be_active=True: triggers at user be_trigger_r, not saved trade config
  ✓ be_active=False: stop_reason never 'be'
  ✓ Open trades walk to data end, capped 30240 min
  ✓ WalkDataError on missing entry candle
  ✓ No DB writes (R2)
  ✓ Performance warning >100, confirm >300

M1 fixed_untp upgrade:
  ✓ Parquet re-walk replaces stored mfe_at_Xh_r
  ✓ Returns stats_be_on / stats_be_off
  ✓ Win = peak_mfe >= target; alive irrelevant (R11)
  ✓ No-limit maps to max_minutes=30240
  ✓ BE On/Off/Difference buttons in results area

M1 untp_overview upgrade:
  ✓ Parquet re-walk replaces stored alive_at_Xh
  ✓ Buckets by stop_reason
  ✓ BE bucket only in BE on walk
  ✓ Old sidebar BE toggle removed

M3 RR Sweep:
  ✓ peak_mfe = max(mfe_r) where elapsed_min <= limit
  ✓ Unalive trades counted if path reached target before stopping
  ✓ Adaptive R steps
  ✓ EV = (wr × target) + (lr × -1.0)
  ✓ Best risk-adjusted = EV / (max_consec_losses + 1)
  ✓ Dead zone EV<0 greyed
  ✓ Session filter instant client-side
  ✓ BE switching triggers one re-fetch per mode, cached

M4 BE Comparison:
  ✓ All trades included (not filtered by saved BE state)
  ✓ Group A: fresh BE on re-walk with user be_trigger_r
  ✓ Group B: fresh BE off re-walk, SL only
  ✓ BE count in Group B always 0
  ✓ Difference column shown

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 7 — MODULE 5 (DIP ANALYSIS) + MODULE 6 (STRATEGY CARD)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: NOT STARTED — prerequisite: Phase 6

Module 5 — Dip Analysis (stats_m5_dip.html):
  Of trades where dip_occurred=True:
  Dip survival rate: what % eventually became winners (pnl_r > 0)
  Avg dip depth in pips and R, avg time of dip from entry.

Module 6 — Strategy Card (stats_m6_strategy.html):
  Headline (DECISION-20): "Optimal hold: Xh · Best TP: YR · EV: +ZR per trade"
    — peak EV from M3 RR Sweep surfaced as single number
  Secondary: best risk-adjusted target, confidence level
  BE benefit: avg mfe_after_be_r vs cost. Hidden when no BE trades.
  Claimed vs Actual (DECISION-19): hidden when no claimed_tp_pips data.

Completion criteria:
  ✓ EV headline = peak EV from M3 RR Sweep (DECISION-20)
  ✓ Dip survival rate uses pnl_r > 0 (not outcome string)
  ✓ mfe_after_be_r = from BE activation to TRADE CLOSE (not UNTP stop)
  ✓ BE section hidden when no BE trades
  ✓ Claimed vs Actual section hidden when no claimed_tp_pips

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 8 — POLISH + BONUS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: NOT STARTED — prerequisite: Phase 7

Polish:
  Navigation, empty states, loading spinners, sample warnings, mobile responsive.

Bonus modules:
  Session performance, day-of-week analysis, entry quality, UNTP path chart per trade.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 10 — CLAIMED TP TRACKING (DECISION-19)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: NOT STARTED — no prerequisite. Add when user ready.

Schema addition (DB migration required):
  claimed_tp_pips (nullable float), claimed_pnl_r (nullable float)
  Both always optional. System works without them.

UI: trade entry form optional fields + channel detail Claimed vs Actual column (hidden by default)
    + Strategy Card gap section (hidden by default).
Gap = claimed_pnl_r - pnl_r (positive = channel overclaimed).