# Backtrack — Architecture Reference

# Authoritative source for schema, domain rules, walk semantics, and field meanings.

# This file does not change unless the architecture changes.

# Bugs, decisions, and session history live in MCP.md.

# Last updated: 2026-03-15

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ STACK & PROJECT STRUCTURE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Python · Flask · SQLite (SQLAlchemy) · pandas · parquet price files

app.py              Flask app entry point, blueprints, init_db
config.py           SECRET_KEY and settings
db.py               SQLAlchemy models: Channel, Trade
data_loader.py      Preloads all parquet files at startup into data_frames dict
utils/
  trade_monitor.py  ⛔ READ-ONLY. Core engine. Never modify.
  mfe_calculator.py Trade walk + UNTP walk. Runs at save time.
  walk_engine.py    ← Phase 6: Query-time parquet re-walk engine. No DB writes.
                      Used by M1 fixed_untp, M1 untp_overview, M3 RR Sweep, M4 BE Compare.
  trade_storage.py  All DB read/write. No Flask, no statistics.
  trade_statistics.py Pure computation. No DB, no Flask.
  trade_validation.py Input validation helpers
  trade_calculations.py Price/pip math helpers
  pip_utils.py      Pip size per symbol. Always use this.
  symbols.py        SYMBOLS list
  datetime_utils.py Datetime parsing helpers
routes/
  save_routes.py       POST /save_trade, GET /channels/list_json
  channel_routes.py    Channel CRUD + trade ops + CSV export
  statistics_routes.py GET /statistics, POST /statistics/overview,
                       POST /statistics/hitrate, POST /statistics/pnl,
                       POST /statistics/sweep (Phase 6),
                       POST /statistics/becompare (Phase 6)
templates/
  index.html        Trade monitor form
  results.html      Monitor output + Save Trade button
  error.html        Global error handler
  channels.html     Channel list page
  channel_detail.html Channel trades table + TP drawer + UNTP section + UNTP drawer
  statistics.html   Statistics hub shell — nav, sidebar, shared JS only (DECISION-18)
  partials/
    stats_m1_overview.html  Module 1 — Overview (Phase 4/5 BUILT; Phase 6 upgrades M1)
    stats_m2_hitrate.html   Module 2 — Hit Rate (Phase 5 BUILT)
    stats_m3_sweep.html     Module 3 — RR Sweep (Phase 6 — replaces old stats_m3_tpsim.html)
    stats_m4_becompare.html Module 4 — BE Comparison (Phase 6 — replaces old stats_m4_sweep.html)
    stats_m5_dip.html       Module 5 — Dip Analysis (Phase 7 — placeholder)
    stats_m6_strategy.html  Module 6 — Strategy Card (Phase 7 — placeholder)
    stats_m7_pnl.html       Module 7 — PnL Report (Phase 5 BUILT)

NOTE: stats_m3_tpsim.html and stats_m4_sweep.html are old placeholder names.
      Rename to stats_m3_sweep.html and stats_m4_becompare.html at Phase 6 start.
      TP Simulator feature was dropped (DECISION-21).

Parquet filename convention:
  Most symbols: {SYMBOL}.parquet (e.g. EURUSD.parquet)
  NAS100 → USTEC.parquet (NAS100 maps to USTEC in filenames)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ CORE PRINCIPLES ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

P1 — User inputs are minimal.
  User provides: symbol, trade_type, entry_time, entry_price, stoploss_price,
  takeprofit_price (optional), limit_price (optional), breakeven settings.
  Everything else is auto-computed at save time.

P2 — pnl_r is the ONLY P&L field.
  hit_tp → +tp_rr_target | hit_sl → -1.0 | hit_be → 0.0 | open/none → NULL
  Never compute P&L from mfe fields or outcome strings.

P3 — Statistics are dynamic, never stored.
  Win rate, net RR, EV are computed at query time from raw trade fields.
  Never written to the DB.

P4 — price_path_captured = False means exclude from ALL statistics.
  Set when mfe_calculator fails or data is unavailable.

P5 — db.create_all() does NOT add columns to existing SQLite tables.
  Any schema change requires: drop trades.db → re-run migration command.
  Migration: python3 -c "from app import app; from db import db; app.app_context().push(); db.drop_all(); db.create_all(); print('Done')"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PIP SIZES — always use pip_utils.get_pip_size(symbol) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

XAUUSD              0.1
XAGUSD              0.01
NAS100, US30        1.0
USOIL, UKOIL        0.1
JPY pairs           0.01
All others          0.0001

Never hardcode pip sizes. pip_utils.py is the single source of truth.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ THE TWO WALKS (save-time) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Both walks share the same candle loop from entry. They run simultaneously at save time.
The trade walk produces realised P&L. The UNTP walk produces analytical data only.

── TRADE WALK ──────────────────────────────────────────────────

Closes on FIRST trigger:

1. TP hit → exit_price=takeprofit_price, outcome='hit_tp', pnl_r=+tp_rr_target
2. SL hit → exit_price=stoploss_price, outcome='hit_sl', pnl_r=-1.0
3. BE hit → exit_price=entry_price, outcome='hit_be', pnl_r=0.0
   (BE = stoploss moved to entry, then price retraces to entry)

Still open (no TP set): outcome='none', pnl_r=NULL, exit_price=last candle close
Still open (TP set):    outcome='open', pnl_r=NULL, exit_price=last candle close

Produces:
  exit_price, outcome_at_user_tp, pnl_r, rr_at_user_tp (alias for pnl_r)
  mfe_pips/r, mfe_at_close_pips/r, time_to_mfe_minutes
  mae_pips/r, time_to_mae_minutes
  retracement_from_mfe_pips/r
  candles_to_resolution, time_to_resolution_minutes
  tp_was_reached, time_to_tp_minutes, peak_rr_at_close
  dip_pips, dip_time_minutes, dip_occurred
  consecutive_adverse_candles, first_candle_direction
  breakeven_triggered, breakeven_sl_price, breakeven_trigger_time_minutes
  mfe_at_breakeven_pips/r, mfe_after_be_pips/r
  time_to_0_5r/1r/1_5r/2r/3r/4r/5r_minutes

── UNTP WALK (save-time) ───────────────────────────────────────

Starts on the SAME candle as trade walk. Never affects pnl_r.
Powers "what if you'd held longer" analytics.
Stored in DB as 56 checkpoint columns + mfe_path_json.

Stop condition based on be_triggered ACTUAL state (not config):
  be_triggered=False → stops when original stoploss_price is hit
  be_triggered=True  → stops when entry_price is retraced

Additional stop: 504h cap (21 days = 30,240 minutes)

For hit_sl: UNTP stops same candle (SL = UNTP stop condition)
For hit_be: UNTP stops same candle (entry retrace = UNTP stop)
For hit_tp: UNTP continues after trade close until its own stop fires

⚠ If BE was configured but never triggered before TP:
  be_triggered=False. UNTP stop = original SL, NOT entry retrace.

Produces: 14 checkpoint snapshots × 4 fields = 56 columns (see UNTP SNAPSHOTS below)
          mfe_path_json (15-min sampled path — display use only in Phase 6+)

IMPORTANT (Phase 6+): The stored 56 columns and mfe_path_json are used for:
  - Channel detail drawer: UNTP window selector, path chart, alive/outcome display
  - mfe_path_json: path chart in UNTP drawer
  NOT used for: MFE classification in statistics (replaced by walk_engine re-walk)

── CANDLE ITERATION ORDER ──────────────────────────────────────

Execute in this exact order every candle:

  a. Update elapsed_minutes
  b. Update R milestones (time_to_0_5r, time_to_1r, etc.)
  c. Dip check (adverse move before first favourable candle)
  d. BE trigger check (if BE active and MFE crossed BE threshold)
  e. SL check (original SL, or entry_price if BE already triggered)
  f. TP check
  g. UNTP snapshot recording (if at a checkpoint)

── POST-WALK CLEANUP (MANDATORY — run AFTER loop, not inside) ──

Dip cleanup:
  if dip_occurred and peak_dip_time >= resolution_candle_time:
    dip_pips = 0; dip_time_minutes = None; dip_occurred = False

BE phantom cleanup:
  if outcome == 'hit_tp' and be_trigger_min == resolution_min:
    breakeven_triggered = False; breakeven_sl_price = None
    breakeven_trigger_time_minutes = None
    mfe_at_breakeven_pips = mfe_at_breakeven_r = None
    mfe_after_be_pips = mfe_after_be_r = None

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 6 — QUERY-TIME WALK ENGINE (walk_engine.py) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

New file added in Phase 6. Used for all statistics that require candle-level MFE precision.
Uses already-loaded data_frames dict — zero disk reads at query time.

Function:
  walk_trade_untp(
      trade: dict,
      data_frames: dict,
      max_minutes: int,          # use 30240 for "No limit" (504h cap)
      be_active: bool,           # True = trigger BE at be_trigger_r
      be_trigger_r: float | None # required when be_active=True
  ) -> dict

Returns:
  peak_mfe_r:     float    highest MFE reached during walk
  peak_mae_r:     float    highest MAE reached during walk
  stop_reason:    str      'sl' | 'be' | 'time_limit' | 'open'
  stopped_at_min: int|None elapsed minutes at stop (None if open)
  path:           list     [[elapsed_min, mfe_r, mae_r], ...] every candle

Stop reasons:
  'sl'         original SL hit → SL bucket in untp_overview
  'be'         BE triggered (price hit be_trigger_r), then entry retraced → BE bucket
               Only possible when be_active=True
  'time_limit' max_minutes reached before natural stop → Open bucket
  'open'       parquet data exhausted → Open bucket (still running)

Error: WalkDataError if entry candle not in parquet → caller excludes trade.

BE rules (DECISION-22):
  be_active=True:  use user-supplied be_trigger_r. Trade's saved BE config is NEVER read.
  be_active=False: walk to original SL only. stop_reason never 'be'.
  Both walks are always fresh from entry candle regardless of saved trade state.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ UNTP SNAPSHOTS — 14 CHECKPOINTS × 4 FIELDS = 56 COLUMNS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Stored in DB at save time. Used for channel detail drawer display only in Phase 6+.
NOT used for MFE classification in statistics from Phase 6 onwards (walk_engine replaces this).

Checkpoints (minutes): 30, 60, 120, 240, 480, 720, 1440, 2880, 4320, 7200, 10080, 14400, 20160, 30240
Keys: 30min, 1h, 2h, 4h, 8h, 12h, 24h, 48h, 72h, 120h, 168h, 240h, 336h, 504h

Per checkpoint:

  mfe_at_Xh_r
    Peak MFE in R during UNTP walk up to this checkpoint.
    Frozen at the UNTP-stop value if walk stopped before checkpoint.
    Does NOT update after UNTP stop.

  mae_at_Xh_r
    Peak MAE in R during UNTP walk. Same freeze semantics.

  outcome_at_Xh
    TRADE outcome at this checkpoint:
      'hit_tp'     trade closed at TP before this checkpoint
      'hit_sl'     trade closed at SL before this checkpoint
      'hit_be'     trade closed at BE before this checkpoint
      'still_open' trade was still running at this checkpoint

  alive_at_Xh
    UNTP walk status at this checkpoint:
      True  = UNTP walk still running
      False = UNTP walk stopped (SL or entry retrace) OR data exhausted

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ UNTP DRAWER — refMfe / refMae ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

resolveUntpRef() — Max mode (permanent — DECISION-14):
  Scans all 14 checkpoints, picks highest mfe_at_Xh_r where alive_at_Xh=True.
  If all alive=False: falls back to t.mfe_r (trade walk peak).
  This is the TP drawer's reference MFE. Never changes based on any user input.

resolveUntpAtWindow(t, targetMins):
  Priority: 1. exact checkpoint match → stored fields.
            2. mfe_path_json walk → last entry where elapsed_min <= targetMins.
            3. nearest checkpoint fallback.
  Used by UNTP view table and UNTP drawer for window-based display.

refMfe = UNTP mfe from selected window (or t.mfe_r if no window / all alive=False)
refMae = UNTP mae from selected window (or t.mae_r if no window)

MFE:MAE ratio denominator:
  hit_tp:          t.mae_r (trade walk, frozen at close)
  hit_sl / hit_be: refMae (UNTP MAE; same value since UNTP stopped same candle)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ SAVE TRADE FLOW ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. User runs monitor → results.html displays outcome
2. "💾 Save Trade" button opens modal (channel dropdown + optional notes)
3. POST /save_trade → save_routes.py
4. At save time (single transaction):
   a. Validate + parse all user-provided fields
   b. Run mfe_calculator.calculate_mfe()
      — Trade walk: entry to close (TP/SL/BE)
      — UNTP walk: simultaneously, continues past trade close
      — Post-walk cleanup (dip phantom, BE phantom)
      — Record 14 checkpoint snapshots
      — Record mfe_path_json (sampled every 15min, += 15 rule)
   c. Compute channel_streak_at_save (ORDER BY entry_time, hit_be=skip)
   d. Set session fields: entry_day_of_week, entry_hour, entry_session
   e. Commit all fields in one transaction
5. Toast response: success or warning if price_path_captured=False

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ DATABASE SCHEMA — COMPLETE FIELD LIST ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── channels ────────────────────────────────────────────────────
channel_id      PK, integer
name            unique, string(120), not null
description     string(500), nullable
color           string(20), default '#4A90D9'
created_at      datetime
is_archived     bool, default False

── trades ──────────────────────────────────────────────────────

User-provided:
  trade_id, channel_id (FK+index), symbol, trade_type
  trade_type values: buy / sell / limit_buy / limit_sell / stop_buy / stop_sell
  entry_time, entry_price, stoploss_price, takeprofit_price (nullable)
  limit_price (nullable — market orders: NULL)
  breakeven_active (bool), breakeven_type ('rr'|'pips'), breakeven_value
  input_type ('prices'|'pips'|'rr')
  notes           nullable — TP drawer notes
  untp_notes      nullable — UNTP drawer notes (SEPARATE from notes) ← added 2026-03-13
  saved_at

TP targets (both stored, NULL if no TP):
  tp_rr_target, tp_pips_target

Pending order context:
  pending_trigger_time, pending_wait_minutes
  pending_order_triggered (True/False/NULL — NULL for market orders)

Trade walk — core excursion (frozen at trade close):
  sl_distance_pips
  mfe_pips, mfe_r, mfe_at_close_pips, mfe_at_close_r
  time_to_mfe_minutes
  mae_pips, mae_r, time_to_mae_minutes
  retracement_from_mfe_pips, retracement_from_mfe_r
  exit_price, candles_to_resolution
  dip_pips, dip_time_minutes, dip_occurred
  consecutive_adverse_candles

Outcome / P&L:
  outcome_at_user_tp   'hit_tp'/'hit_sl'/'hit_be'/'open'/'none'
  pnl_r                +tp_rr_target / -1.0 / 0.0 / NULL
  rr_at_user_tp        alias for pnl_r
  time_to_resolution_minutes, tp_was_reached, time_to_tp_minutes, peak_rr_at_close

Breakeven:
  breakeven_triggered (bool), breakeven_sl_price
  breakeven_trigger_time_minutes
  mfe_at_breakeven_pips, mfe_at_breakeven_r
  mfe_after_be_pips, mfe_after_be_r  ← trade walk until TRADE CLOSE, not UNTP

R milestone timing (NULL = never reached during trade walk):
  time_to_0_5r_minutes, time_to_1r_minutes, time_to_1_5r_minutes
  time_to_2r_minutes, time_to_3r_minutes, time_to_4r_minutes, time_to_5r_minutes

UNTP snapshots (56 columns, 14 × 4):
  mfe_at_{X}_r, mae_at_{X}_r, outcome_at_{X}, alive_at_{X}
  where X ∈ {30min,1h,2h,4h,8h,12h,24h,48h,72h,120h,168h,240h,336h,504h}
  NOTE: Used for channel detail drawer display only in Phase 6+.
        Statistics MFE classification uses walk_engine parquet re-walk (DECISION-22).

Entry quality:
  first_candle_direction   'favour'/'against'/'neutral'
  consecutive_adverse_candles (int)
  avg_candle_size_pips_at_entry

Channel streak:
  channel_streak_at_save   positive=wins, negative=losses, 0=first

Session context:
  entry_day_of_week   0=Mon…4=Fri
  entry_hour          0–23
  entry_session       'asian'/'london'/'overlap'/'new_york'/'off_hours'

Integrity:
  price_path_captured   True=reliable; False=exclude from all stats

UNTP path:
  mfe_path_json   [[elapsed_min, mfe_r, mae_r, untp_alive], ...]
  NOTE: 15-min sampled. Used for drawer path chart. Phase 6+ uses candle-level re-walk for stats.

Future optional fields (Phase 10 — DECISION-19, not yet added):
  claimed_tp_pips   nullable float — channel's advertised TP in pips
  claimed_pnl_r     nullable float — channel's claimed P&L in R
  Both always nullable. DB migration required when added. System works without them.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ROUTE MAP ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GET  /                       index.html — monitor form
POST /monitor_trade          run monitor → results.html
POST /save_trade             save to DB
GET  /channels/list_json     channel list JSON (for modal)

GET  /channels               channels list page
POST /channels/create        create channel
POST /channels/<id>/rename   rename
POST /channels/<id>/archive  archive
POST /channels/<id>/unarchive unarchive
POST /channels/<id>/delete   delete + all trades
GET  /channels/<id>          channel detail page
GET  /channels/<id>/export   CSV download

POST /trades/<id>/delete     delete trade
POST /trades/<id>/move       move trade to different channel
POST /trades/<id>/notes      update TP drawer notes (AJAX, returns JSON)
POST /trades/<id>/untp-notes update UNTP drawer notes (AJAX, returns JSON)

GET  /statistics             statistics hub
POST /statistics/overview    Module 1 computation (JSON) — Phase 6 upgrades fixed_untp + untp_overview
POST /statistics/symbols     symbol filter options (JSON)
POST /statistics/hitrate     Module 2 hit rate breakdown (JSON) — Phase 5
POST /statistics/pnl         Module 7 PnL report (JSON) — Phase 5
POST /statistics/sweep       Module 3 RR Sweep — path array per trade (JSON) — Phase 6
POST /statistics/becompare   Module 4 BE Comparison — aggregated groups (JSON) — Phase 6

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ JS RULES — channel_detail.html ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const in renderDrawerContent is in TDZ until its declaration line.
Any forward reference crashes at runtime (not parse time).
Before adding any const: scan the entire function for existing uses.

Strict declaration order in renderDrawerContent:
  DAYS / streakVal / _outcome
  → _streakIsNeutral / streakDisplay
  → ref / _refMfe / _refMae / _refStopped
  → _dip / _advCandles
  → shapeName (+ shape vars)
  → metrics block
  → refLabel
  → innerHTML assignment

show-pips class on <body> controls RR/Pips toggle (CSS-driven, no JS rewrite).

UNTP drawer (#untpDrawer) is a completely separate HTML element from TP drawer (#tradeDrawer).
They have independent Escape handlers, overlays, and open/close state.
Never render UNTP content inside #tradeDrawer.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ IMPLEMENTATION PITFALLS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

These are hard-won from production bugs. Full detail in MCP.md bugs_fixed.

P1  hit_be = SKIP in streak (not a loss). Do not revert.
P2  Streak ORDER BY entry_time, not saved_at.
P3  mfe_path sampling: use += 15, not = elapsed_min (causes drift).
P4  Post-walk cleanup required for dip and BE on wide-candle TP trades.
P5  MFE:MAE denominator for hit_tp = t.mae_r (trade walk), not UNTP MAE.
P6  UNTP denominator = alive_at_Xh=True for Phase 4/5 stored-column queries only.
    Phase 6+ uses walk_engine — no alive gate, denominator = all evaluated trades.
P7  MAE Pressure = t.mae_r only (not UNTP MAE).
P8  JS TDZ: scan renderDrawerContent in full before adding any const.
P9  mfe_after_be_r is from BE activation to TRADE CLOSE, not UNTP stop.
P10 UNTP stop condition at save time = be_triggered ACTUAL value, not breakeven_active config.
    If BE was configured but TP fired first: be_triggered=False, UNTP uses SL stop.
P11 sell dip: measured as price ABOVE entry, not below.
P12 db.create_all() never adds columns. Any schema change = delete trades.db.
P13 UNTP bucket definition for channel detail (PERMANENT — DECISION-12):
      Running = alive=true at window — regardless of MFE sign (positive OR negative)
      Loss    = alive=false AND be_triggered=false → PnL -1.0
      BE      = alive=false AND be_triggered=true  → PnL  0.0
    No "Win" concept in UNTP. TP outcome is irrelevant to UNTP buckets.
P14 UNTP notes vs TP notes are always separate (DECISION-13):
    notes → POST /trades/<id>/notes → Trade.notes (TP drawer)
    untp_notes → POST /trades/<id>/untp-notes → Trade.untp_notes (UNTP drawer)
    Never write TP notes to untp_notes or vice versa.
P15 UNTP drawer is a separate HTML element (#untpDrawer):
    Never render UNTP content inside #tradeDrawer.
P16 walk_engine BE logic (DECISION-22):
    be_trigger_r is always user-supplied per request. Never read trade.breakeven_active or
    trade.breakeven_value. Both walk modes (be_active=True/False) are fresh re-walks.
    Trade's breakeven_triggered column is irrelevant to walk_engine.
P17 fixed_untp win rule (BUG-16, DECISION-22):
    Phase 4/5: win = mfe_at_Xh_r >= target (alive_at_Xh irrelevant — stored column).
    Phase 6+:  win = peak_mfe_r >= target (alive irrelevant — parquet re-walk result).
    Same rule either way. alive_at_Xh must NEVER gate win/loss classification.