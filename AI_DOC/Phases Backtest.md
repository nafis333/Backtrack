# Backtrack — Phased Implementation Plan

# What gets built, in what order, with what completion criteria.

# Phase statuses and session notes live in MCP.md.

# Last updated: 2026-03-15

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE STATUS SUMMARY (detail in MCP.md) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Phase 1   DB + Save Trade                         COMPLETE
Phase 2   Channel UI + Drawer                      COMPLETE
Phase 3   Calculator Hardening                     COMPLETE — 135/135 tests passing
Phase 4   Statistics Hub + Modules 1 & 2           COMPLETE
Phase 5   Module 2 (Hit Rate) + Module 7 (PnL)    COMPLETE
Phase 6   Full Simulator Suite                     NOT STARTED — prerequisite: Phase 5
Phase 7   Module 5 (Dip) + Module 6 (Strategy)    NOT STARTED — prerequisite: Phase 6
Phase 8   Polish + Bonus                           NOT STARTED — prerequisite: Phase 7
Phase 10  Claimed TP Tracking                      NOT STARTED — no prerequisite

Current focus: Phase 6 — Full Simulator Suite.
Build order: walk_engine.py → M1 upgrade → M3 RR Sweep → M4 BE Comparison.

Files needed per phase:
  Phase 6+: ask Claude which files are needed at session start

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 1 — DATABASE FOUNDATION & SAVE TRADE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: COMPLETE — DB migration done 2026-03-14. All items verified.

Files delivered: db.py, utils/mfe_calculator.py, routes/__init__.py, routes/save_routes.py, app.py, templates/results.html

What it builds:
  SQLAlchemy Channel + Trade models with all 56 UNTP columns.
  mfe_calculator: trade walk + UNTP walk running simultaneously.
  POST /save_trade route: validates inputs, runs calculator, commits trade.
  GET /channels/list_json: channel dropdown for save modal.
  results.html: monitor output with Save Trade button + modal.

Completion criteria:
  ✓ All trade fields populated correctly after save
  ✓ mfe_path_json sampled every 15min with += 15 rule
  ✓ 14 UNTP snapshots populated (56 columns)
  ✓ channel_streak_at_save correct (entry_time order, hit_be=skip)
  ✓ price_path_captured=False on data gaps (no crash)
  ✓ Pending orders: triggered vs expired handled
  ✓ Post-walk cleanup for dip and BE phantoms
  ✓ DB migration run, old trades.db deleted

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 2 — CHANNEL UI + TRADE DETAIL DRAWER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: COMPLETE — P2-GAP-1 and P2-GAP-2 both closed.

Files delivered: routes/channel_routes.py, utils/trade_storage.py, templates/channels.html, templates/channel_detail.html

What it builds:
  /channels list with per-channel stats (trade count, win rate, net R).
  /channels/<id> detail page with trades table.
  Trade detail drawer: slides in on row click, keyboard nav (←→), Esc close.
  RR / Pips toggle: pill button, CSS-driven, re-renders open drawer.
  PnL summary bar: net R, win rate, wins, losses, evaluated, excluded count.
  UNTP MFE window selector: 14 checkpoints + Max mode.
  Trade Analysis section: shape, MFE:MAE, MFE utilisation, exit efficiency, MAE pressure.
  Notes inline edit: AJAX POST /trades/<id>/notes.
  Channel CRUD: create, rename, archive, unarchive, delete.
  Trade ops: delete, move, CSV export.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 3 — CALCULATOR HARDENING ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: COMPLETE — all 16 EC cases verified by test suite. 135/135 tests passing.

Files: utils/mfe_calculator.py, utils/trade_storage.py

Edge cases verified:
  EC-1  Pending order never triggers: price_path_captured=False, no crash
  EC-2  Trade at end of parquet file: walk stops gracefully, outcome=open/none
  EC-3  BE at very high R (7R+): triggers correctly if price reaches level
  EC-4  SELL dip direction: measured as price ABOVE entry, not below
  EC-5  Trade resolves before 30min: all 14 snapshots frozen at resolved state
  EC-6  Single-candle trade: mfe_path gets exactly 1 entry, no index errors
  EC-7  UNTP be_triggered=False: stops at original SL, NOT entry retrace
  EC-8  UNTP be_triggered=True: stops at entry retrace, NOT original SL
  EC-9  UNTP alive=True at 504h: if neither stop fires, all 14 alive=True
  EC-10 Post-walk cleanup: dip cleared when peak_dip_time >= resolution_time
  EC-11 Post-walk cleanup: BE cleared when outcome=hit_tp AND be_min=resolution_min
  EC-12 mfe_path forced entry at trade close and UNTP stop; deduplicated
  EC-13 mfe_after_be_r stops accumulating once trade fully closed
  EC-14 UNTP MFE/MAE frozen immediately on stop (no further candle inflation)
  EC-15 Symbol not in data_frames: ValueError caught, price_path_captured=False
  EC-16 SL distance = 0: explicit ValueError before walk starts

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 4 — STATISTICS HUB + MODULES 1 & 2 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: COMPLETE — all items verified. 4-mode redesign delivered. BUG-16 fixed.

Files: utils/trade_statistics.py, routes/statistics_routes.py,
       templates/statistics.html (shell), templates/partials/stats_m1_overview.html

─────────────────────────────────────────────────────────────
### Phase 4 — Module 1: Statistics Hub + Overview [DELIVERED]

GET /statistics: hub page with channel selector, TP mode, time limit options.
POST /statistics/overview: JSON API returning Module 1 computed stats.
Module 1 display: win/loss/open counts, net RR, win rate, excluded count,
  equity curve, drawdown curve, avg MFE/MAE, streaks.

Modes delivered (Phase 4/5, pre-Phase-6):
  original_tp:  win=hit_tp; loss=hit_sl/hit_be; time limit disabled.
  fixed_tp:     win=mfe_r>=target (trade walk peak); time limit disabled.
  fixed_untp:   win=mfe_at_Xh_r>=target (stored snapshot); time limit required.
                NOTE: Phase 6 upgrades to candle-level parquet re-walk (DECISION-22).
  untp_overview: Open/SL/BE distribution; time limit required.
                NOTE: Phase 6 upgrades to candle-level parquet re-walk (DECISION-22).

Phase 6 upgrades to M1:
  fixed_untp:   replaced by parquet re-walk via walk_engine.walk_trade_untp()
  untp_overview: replaced by parquet re-walk via walk_engine.walk_trade_untp()
  Both modes get: BE On / BE Off / Difference result views (drawer-style)
  Time limit dropdown gains "No limit" option (= 504h cap)
  Old sidebar BE toggle (All/BE Active/No BE) removed

─────────────────────────────────────────────────────────────
### Phase 4 — Module 2: UNTP Dual-Section View [DELIVERED 2026-03-13]

Page layout:
  Toggle pill in table toolbar: "TP View" / "UNTP View"
  TP View (default): existing PnL bar + table + trade walk drawer
  UNTP View: UNTP section header + UNTP PnL bar + UNTP table

UNTP window controls:
  Slider: snaps to 14 checkpoints (30min → 504h), index 0–13
  Numeric input: accepts any minutes, walks mfe_path_json for arbitrary resolution
  Slider and input box stay in sync bidirectionally

UNTP PnL bar:
  Running = alive=true at window (any MFE)
  Loss (SL) = alive=false AND be_triggered=false → PnL -1.0
  BE = alive=false AND be_triggered=true → PnL 0.0
  Net R = sum of running(floating mfe@window) + losses(-1.0) + bes(0.0)
  No "Win" concept. No win rate shown.

UNTP drawer (#untpDrawer — completely separate HTML element):
  Outcome hero, UNTP Peak All Time, UNTP @ Window, Entry Geometry,
  R Milestones, BE section, Pending Order, UNTP Notes, Data

─────────────────────────────────────────────────────────────
### Phase 4 — Statistics Redesign: 4-Mode System [P5-PREREQ-1 — DELIVERED 2026-03-15]

Statistics.html split into shell + 7 partials (DECISION-18).
4 modes implemented. fixed_untp win semantics corrected (BUG-16).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 5 — MODULE 2 (HIT RATE) + MODULE 7 (PNL REPORT) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: COMPLETE — Module 2 and Module 7 delivered and verified. P2-GAP-1 closed.

Module 2 — Hit Rate Analysis:
  Breakdown by: symbol, trade_type, session, day-of-week
  Each breakdown row: win count, loss count, win rate, net RR
  Uses same 4-mode system as Module 1
  fixed_untp mode: win = mfe_at_Xh_r >= target (alive irrelevant — BUG-16)
  Partial: templates/partials/stats_m2_hitrate.html

Module 7 — PnL Report:
  Equity curve: cumulative sum of pnl_r over time (ORDER BY entry_time)
  Weekly + monthly net R totals (zero-trade weeks shown as 0.0)
  Win streak, loss streak (hit_tp / hit_sl; hit_be = skip)
  Per-symbol net RR (sums to total)
  Partial: templates/partials/stats_m7_pnl.html

Completion criteria:
  ✓ Hit rate win = outcome='hit_tp' (original_tp mode)
  ✓ Hit rate win = mfe_at_Xh_r >= target (fixed_untp mode; alive irrelevant)
  ✓ Equity curve = sum of pnl_r ordered by entry_time
  ✓ Weekly totals sum to monthly total
  ✓ hit_be excluded from streak in PnL report
  ✓ Per-symbol net RR sums to overall total
  ✓ CSV export includes all 56 UNTP columns + mfe_path_json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 6 — FULL SIMULATOR SUITE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: NOT STARTED — prerequisite: Phase 5.

Core purpose: mathematically find the optimal TP for any channel's signals,
at candle-level precision, with or without breakeven simulation,
using already-loaded parquet data (zero disk I/O at query time).

─────────────────────────────────────────────────────────────
SHARED ENGINE — utils/walk_engine.py
─────────────────────────────────────────────────────────────

New file. Used by M1 upgrade, M3 RR Sweep, M4 BE Comparison.

  walk_trade_untp(
      trade: dict,
      data_frames: dict,       # already-loaded parquets from data_loader
      max_minutes: int,        # always required; use 30240 for "no limit" (504h cap)
      be_active: bool,         # True = trigger BE at be_trigger_r
      be_trigger_r: float | None  # required when be_active=True
  ) -> dict

Returns:
  peak_mfe_r:     float         highest MFE reached during walk
  peak_mae_r:     float         highest MAE reached during walk
  stop_reason:    str           'sl' | 'be' | 'time_limit' | 'open'
  stopped_at_min: int | None    elapsed minutes at stop (None if open)
  path:           list          [[elapsed_min, mfe_r, mae_r], ...] every candle

Stop reason mapping:
  'sl'          original SL hit → untp_overview SL bucket
  'be'          BE triggered (price hit be_trigger_r) then entry retraced → BE bucket
                Only possible when be_active=True
  'time_limit'  max_minutes reached before natural stop → untp_overview Open bucket
  'open'        parquet data exhausted before any stop (trade still running) → Open bucket

Error handling:
  WalkDataError raised if entry candle not found in parquet
  Caller catches it, excludes trade, adds to excluded list with reason 'no_price_data'

BE logic rules (DECISION-22):
  be_active=True: trigger BE when price reaches be_trigger_r in favour,
    then stop when price retraces to entry. Uses user-supplied be_trigger_r only.
    Trade's breakeven_active / breakeven_value / breakeven_type never read.
  be_active=False: walk to original SL only. BE never triggers.
  Both walks are always fresh re-walks from entry candle.
  Same rules apply to ALL trades regardless of their saved BE configuration.

Performance:
  data_frames already loaded at app startup — zero disk reads
  One DataFrame slice per trade (entry_time to stop) — trivial memory
  No DB writes ever (R3)
  Performance guard: warn at >100 trades, require confirmation at >300

─────────────────────────────────────────────────────────────
M1 UPGRADE — fixed_untp and untp_overview (parquet re-walk)
─────────────────────────────────────────────────────────────

Route: POST /statistics/overview — same route, same response shape.
Server now calls walk_trade_untp() twice per trade (BE on + BE off).
Returns two groups: stats_be_on / stats_be_off (replaces old stats_all/stats_be_active/stats_no_be).

fixed_untp classification per group:
  Win = peak_mfe_r >= target
  Loss = peak_mfe_r < target
  Excluded = WalkDataError (shown in excluded_count)

untp_overview classification per group:
  Open = stop_reason in ('time_limit', 'open')
  SL   = stop_reason == 'sl'
  BE   = stop_reason == 'be' (only in BE on walk; never in BE off walk)

UI changes (stats_m1_overview.html):
  Results area: BE On / BE Off / Difference buttons appear after run
  BE On → renders stats_be_on
  BE Off → renders stats_be_off
  Difference → slides in comparison drawer page (metrics side by side)
  Time limit dropdown gains "No limit" option at top
  BE Simulation input: be_trigger_r visible when BE On selected
  Old sidebar BE toggle (All/BE Active/No BE) removed entirely

─────────────────────────────────────────────────────────────
M3 — RR SWEEP (stats_m3_sweep.html — replaces old stats_m3_tpsim.html placeholder)
─────────────────────────────────────────────────────────────

Answers: "What is the optimal TP target for this channel within my time window?"

Sidebar inputs (separate be_trigger_r from M1):
  Time Limit: slider (any minutes 1–30240) + numeric input (syncs)
  BE Simulation: BE On (trigger R: [____]) / BE Off radio buttons

Server request: channel filters + be_active + be_trigger_r + max_minutes
Server response per trade:
  { trade_id, entry_time, session, path: [[elapsed_min, mfe_r, mae_r], ...] }
Client holds full path array permanently — all sweep calculations client-side.

Per trade per time limit (client):
  peak_mfe = max(mfe_r for path where elapsed_min <= time_limit_min)
  peak_mae = max(mae_r for path where elapsed_min <= time_limit_min)

R target sweep — adaptive steps (client-side):
  0.25R steps: 0.25R → 3.0R
  0.50R steps: 3.0R → 6.0R
  1.00R steps: 6.0R → max(peak_mfe) rounded up to step

Win/loss per target:
  Win  = peak_mfe >= target
  Loss = peak_mfe < target
  Denominator = ALL evaluated trades (no alive filter)

Per target row:
  Target R         sweep value
  Trades           count evaluated
  Wins             peak_mfe >= target
  Win Rate         wins / trades × 100
  EV               (win_rate × target) + (loss_rate × -1.0)
  Net R            sum(+target for wins, -1.0 for losses)
  Avg MAE before   wins only: max(mae) in path up to first target hit
  MAE:Target       avg_mae_before / target
  Median TTT        wins only: median elapsed_min when mfe first crossed target
  Max Consec Loss  streak in entry_time order (R5 rule — hit_be=skip)
  Early Exit %     wins where 75% of target hit within first 25% of time limit
  Confidence       Red <20 / Yellow 20-49 / Green 50+
  Verdict          ★ Best EV / ◆ Best risk-adjusted
  Dead zone        EV < 0 → greyed

Best risk-adjusted: EV / (max_consec_losses + 1)

Filters (all instant, client-side):
  Time limit slider re-sweeps all rows instantly
  Session: All / Asian / London / Overlap / New York

BE On/Off switching:
  Switching BE mode → new server request; result cached per mode client-side
  Switching back to cached mode → no re-fetch
  Difference button → slides in comparison drawer showing per-target changes

─────────────────────────────────────────────────────────────
M4 — BE COMPARISON (stats_m4_becompare.html — replaces old stats_m4_sweep.html placeholder)
─────────────────────────────────────────────────────────────

Answers: "Does adding a breakeven stop help or hurt this channel's signals?"

Sidebar inputs (separate be_trigger_r from M1 and M3):
  Time Limit: dropdown (No limit + 14 options)
  BE Trigger R: [____] (always required for this module)

Server: runs walk_trade_untp() twice per trade — BE on and BE off.
Returns two groups at user's time limit:
  Group A (BE on):  fresh re-walk with user's be_trigger_r
  Group B (BE off): fresh re-walk, SL only

Per group output:
  Open count, SL count, BE count (always 0 for Group B)
  Avg peak MFE, avg peak MAE
  Net R, max consecutive stops

UI: BE On / BE Off / Difference pages (same drawer-style navigation as M1 and M3)

Difference page:
  Per metric: Group B - Group A, green = BE off better, red = BE on better

All trades included — not filtered by original trade's BE state.

─────────────────────────────────────────────────────────────
ROUTES
─────────────────────────────────────────────────────────────

POST /statistics/overview    upgraded M1 (stats_be_on + stats_be_off per trade)
POST /statistics/sweep       M3 RR sweep (path per trade, one BE mode per request)
POST /statistics/becompare   M4 BE comparison (both walks, aggregated per group)
POST /statistics/hitrate     M2 hit rate (already exists — Phase 5)
POST /statistics/pnl         M7 PnL report (already exists — Phase 5)

─────────────────────────────────────────────────────────────
COMPLETION CRITERIA
─────────────────────────────────────────────────────────────

Walk Engine:
  ✓ data_frames already in memory — zero disk reads per request
  ✓ stop_reason correctly set for all four cases (sl/be/time_limit/open)
  ✓ be_active=True: BE triggers at user be_trigger_r, not trade's saved config
  ✓ be_active=False: walk to original SL only, stop_reason never 'be'
  ✓ Open trades walk to parquet end, capped at 504h
  ✓ WalkDataError raised and caught when entry candle absent
  ✓ No DB writes (R3)
  ✓ Performance warning at >100 trades, confirm at >300

M1 Upgrade (fixed_untp):
  ✓ Parquet re-walk replaces stored mfe_at_Xh_r
  ✓ Returns stats_be_on / stats_be_off
  ✓ Win = peak_mfe >= target; alive irrelevant
  ✓ "No limit" maps to max_minutes=30240
  ✓ BE On/Off/Difference buttons in results area

M1 Upgrade (untp_overview):
  ✓ Parquet re-walk replaces stored alive_at_Xh
  ✓ Buckets: Open / SL / BE by stop_reason
  ✓ BE bucket only appears in BE on walk
  ✓ Old sidebar BE toggle removed

M3 RR Sweep:
  ✓ peak_mfe = max(mfe_r) in path where elapsed_min <= limit
  ✓ Unalive trades counted if path reached target before stopping
  ✓ Adaptive R steps (0.25 → 3R, 0.5 → 6R, 1.0 beyond)
  ✓ EV = (wr × target) + (lr × -1.0)
  ✓ Best risk-adjusted = EV / (max_consec_losses + 1)
  ✓ Dead zone EV < 0 greyed
  ✓ Session filter instant client-side
  ✓ BE switching triggers one re-fetch per mode, then cached

M4 BE Comparison:
  ✓ All trades included (not filtered by saved BE state)
  ✓ Group A: fresh BE on re-walk with user be_trigger_r
  ✓ Group B: fresh BE off re-walk, SL only
  ✓ Difference column shown
  ✓ BE count in Group B always 0

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 7 — MODULE 5 (DIP ANALYSIS) + MODULE 6 (STRATEGY CARD) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: NOT STARTED — prerequisite: Phase 6.

Module 5 — Dip Analysis (stats_m5_dip.html):
  Of trades where dip_occurred=True:
  Dip survival rate: what % eventually became winners
  Avg dip depth in pips and R
  Avg time of dip from entry
  Win = pnl_r > 0 (not outcome string)

Module 6 — Strategy Card (stats_m6_strategy.html):
  Primary purpose: answer "what is the mathematically optimal TP for this channel?"

  Headline (DECISION-20):
    "Optimal hold: Xh · Best TP: Y R · EV: +Z R per trade"
    — peak EV point from M3 RR Sweep, surfaced as single number headline

  Secondary metrics:
    Best risk-adjusted target (◆ from M3)
    Confidence level (trade count)
    BE benefit: avg mfe_after_be_r vs cost (hit_be count)
      BE section only shown when BE trades exist in dataset

  Claimed vs Actual gap (DECISION-19):
    Shown only when claimed_tp_pips populated on any trade in filter
    Hidden by default

Completion criteria:
  ✓ EV headline = peak EV from M3 RR Sweep (DECISION-20)
  ✓ Dip survival rate uses pnl_r > 0 (not outcome string)
  ✓ mfe_after_be_r = from BE activation to TRADE CLOSE (not UNTP stop)
  ✓ BE section hidden when no BE trades exist
  ✓ Claimed vs Actual section hidden when no claimed_tp_pips data exists

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 8 — POLISH + BONUS MODULES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: NOT STARTED — prerequisite: Phase 7.

Polish:
  Navigation: all pages reachable from all other pages
  Empty states: no trades, no channels, no data for filter
  Loading spinners during all computation
  Sample size warning at < 20 trades (every module)
  price_path_captured=False excluded everywhere with count shown
  Performance warning if trade count > 500 in walk engine
  Mobile responsive layouts

Bonus modules:
  Session performance: win rate / net RR by session (asian/london/overlap/new_york)
  Day-of-week analysis: entry_day_of_week breakdown
  Entry quality module: first_candle_direction + avg_candle_size analysis
  UNTP path chart per trade:
    Trade close as vertical line
    UNTP continuation as dashed line post-close
    untp_alive=0 segment in different colour
    Data from mfe_path_json

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 9 — CLAIMED TP TRACKING (DEFERRED — DECISION-19) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STATUS: NOT STARTED — no prerequisite. Add when user is ready to track channel claims.

Purpose:
  Compare channel's claimed TP/PnL against mathematically computed actual performance.
  Exposes the gap between what channels advertise and what their signals actually deliver.

Schema addition (DB migration required):
  claimed_tp_pips   nullable float — channel's advertised TP distance in pips
  claimed_pnl_r     nullable float — channel's claimed P&L in R for this trade
  Both fields are always optional. System works fully without them.

UI changes:
  Trade entry form: optional "Claimed TP (pips)" and "Claimed PnL (R)" fields
  Channel detail table: "Claimed vs Actual" column — hidden unless populated
  Strategy Card (Module 6): claimed vs actual gap section — hidden unless populated

No computation changes — claimed fields are display only.

Completion criteria:
  ✓ claimed_tp_pips / claimed_pnl_r nullable in schema — never required
  ✓ Claimed vs Actual column hidden when no trades have claimed data
  ✓ Gap = claimed_pnl_r - pnl_r (positive = channel overclaimed)
  ✓ No existing feature breaks when fields are null