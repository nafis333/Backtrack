# ARCH — schema, walk semantics, field meanings, routes. Append-only on architecture change.

## Stack
Python · Flask · SQLite (SQLAlchemy) · pandas · parquet price files

## Project Structure
app.py                    Flask entry point, blueprints, init_db
config.py                 SECRET_KEY
db.py                     SQLAlchemy models: Channel, Trade. Trade.to_dict() is only DB→stats path.
data_loader.py            Module-level: loads all 39 parquets into data_frames dict at startup.
                          Keys = uppercase symbol strings. Used by mfe_calculator + walk_engine.
utils/
  trade_monitor.py        READ-ONLY. Never modify.
  mfe_calculator.py       Save-time walk engine. Both trade + UNTP walks simultaneously.
  walk_engine.py          Query-time re-walk engine (Phase 6). No DB writes. Uses data_frames.
  trade_storage.py        All DB read/write. No Flask, no statistics.
  trade_statistics.py     Pure computation. No DB, no Flask. Accepts trade dicts.
  trade_validation.py     Monitor-time input validation.
  trade_calculations.py   Price lookups from parquet (monitor-time only). get_file_name() NAS100→USTEC.
  pip_utils.py            get_pip_size(symbol) — authoritative pip sizes.
  symbols.py              SYMBOLS list (39 total).
  datetime_utils.py       Datetime parsing helpers for monitor form.
routes/
  save_routes.py          POST /save_trade, GET /channels/list_json
  channel_routes.py       Channel CRUD + trade ops
  statistics_routes.py    All statistics APIs
templates/
  statistics.html         Shell only — 7 partials via Jinja2 include (DECISION-18). FROZEN.
  partials/
    stats_m1_overview.html   Phase 4/5 BUILT
    stats_m2_hitrate.html    Phase 5 BUILT
    stats_m3_sweep.html      Phase 6 — rename from stats_m3_tpsim.html
    stats_m4_becompare.html  Phase 6 — rename from stats_m4_sweep.html
    stats_m5_dip.html        Phase 7 placeholder
    stats_m6_strategy.html   Phase 7 placeholder
    stats_m7_pnl.html        Phase 5 BUILT

## The Two Walks (save-time — mfe_calculator.py)

TRADE WALK — resolves actual trade:
  Closes on first: TP → SL → BE
  hit_tp: exit=takeprofit_price, outcome=hit_tp, pnl_r=+tp_rr_target
  hit_sl: exit=stoploss_price,   outcome=hit_sl, pnl_r=-1.0
  hit_be: exit=entry_price,      outcome=hit_be, pnl_r=0.0
  open/none: pnl_r=NULL, exit=last candle close

UNTP WALK — runs simultaneously, never affects pnl_r:
  Stop condition (based on be_triggered ACTUAL state, not config):
    be_triggered=False → stops at original stoploss_price
    be_triggered=True  → stops at entry_price retrace
  Also stops at 504h cap (30240 min).
  hit_sl/hit_be: UNTP stops same candle as trade.
  hit_tp: UNTP continues after trade close until its own stop fires.
  If BE configured but TP fired first: be_triggered=False, UNTP stop = original SL.

WALK ENGINE (query-time — walk_engine.py, Phase 6+):
  Fresh re-walk per trade using data_frames (zero disk I/O).
  be_active=True:  trigger BE at user-supplied be_trigger_r. trade.breakeven_* never read.
  be_active=False: walk to original SL only. stop_reason never 'be'.
  Returns: peak_mfe_r, peak_mae_r, stop_reason, stopped_at_min, path [[min,mfe,mae],...]

## Database Schema — trades table (key fields)

User-provided:
  symbol, trade_type (buy/sell/limit_buy/limit_sell/stop_buy/stop_sell)
  entry_time, entry_price, stoploss_price, takeprofit_price (nullable)
  limit_price (nullable), breakeven_active, breakeven_type, breakeven_value
  notes (TP drawer), untp_notes (UNTP drawer — separate column), saved_at

Outcome/P&L:
  outcome_at_user_tp   hit_tp/hit_sl/hit_be/open/none
  pnl_r                +tp_rr_target / -1.0 / 0.0 / NULL (R1 — authoritative)
  tp_rr_target, tp_pips_target

Trade walk excursion (frozen at trade close):
  sl_distance_pips
  mfe_pips, mfe_r, mfe_at_close_pips, mfe_at_close_r
  mae_pips, mae_r
  exit_price, candles_to_resolution, time_to_resolution_minutes
  dip_pips, dip_time_minutes, dip_occurred
  consecutive_adverse_candles, first_candle_direction

Breakeven:
  breakeven_triggered, breakeven_sl_price, breakeven_trigger_time_minutes
  mfe_at_breakeven_pips/r, mfe_after_be_pips/r (trade walk to TRADE CLOSE only)

R milestones (NULL if never reached):
  time_to_0_5r/1r/1_5r/2r/3r/4r/5r_minutes

UNTP snapshots (56 columns = 14 checkpoints × 4 fields):
  mfe_at_{X}_r, mae_at_{X}_r, outcome_at_{X}, alive_at_{X}
  X ∈ {30min,1h,2h,4h,8h,12h,24h,48h,72h,120h,168h,240h,336h,504h}
  Phase 6+: used for channel detail drawer display only. Statistics uses walk_engine.

Entry quality:
  first_candle_direction (favour/against/neutral)
  consecutive_adverse_candles, avg_candle_size_pips_at_entry

Session context:
  entry_day_of_week (0=Mon…4=Fri), entry_hour (0-23)
  entry_session (asian/london/overlap/new_york/off_hours)

Other:
  channel_streak_at_save (positive=wins, negative=losses, 0=first)
  price_path_captured (True=reliable, False=exclude from all stats)
  mfe_path_json [[elapsed_min, mfe_r, mae_r, untp_alive], ...] 15-min sampled

Future/deferred (Phase 10 — DECISION-19, not yet added):
  claimed_tp_pips (nullable float), claimed_pnl_r (nullable float)

## Route Map
GET  /                          index.html monitor form
POST /monitor_trade             run monitor → results.html
POST /save_trade                save to DB
GET  /channels/list_json        channel list for save modal
GET  /channels                  channel list page
POST /channels/create           create channel
POST /channels/<id>/rename      rename
POST /channels/<id>/archive     archive
POST /channels/<id>/unarchive   unarchive
POST /channels/<id>/delete      delete + all trades
GET  /channels/<id>             channel detail page
GET  /channels/<id>/export      CSV download (all 56 UNTP cols + mfe_path_json)
POST /trades/<id>/delete        delete trade
POST /trades/<id>/move          move trade (recalculates streak both channels)
POST /trades/<id>/notes         TP drawer notes → Trade.notes
POST /trades/<id>/untp-notes    UNTP drawer notes → Trade.untp_notes
GET  /statistics                statistics hub
POST /statistics/overview       Module 1 — Phase 6: fixed_untp/untp_overview use walk_engine
POST /statistics/symbols        symbol filter options
POST /statistics/hitrate        Module 2 hit rate breakdown
POST /statistics/pnl            Module 7 PnL report (uses pnl_r directly, mode-agnostic)
POST /statistics/sweep          Module 3 RR Sweep — path array per trade (Phase 6)
POST /statistics/becompare      Module 4 BE Comparison — aggregated groups (Phase 6)

## Statistics Modes
original_tp:    win=hit_tp, loss=hit_sl/hit_be, time limit disabled
fixed_tp:       win=mfe_r>=target (trade walk peak), time limit disabled
fixed_untp:     win=peak_mfe_r>=target (alive irrelevant), time limit or no-limit
                Phase 6+: parquet re-walk via walk_engine
untp_overview:  Open/SL/BE distribution, no target, time limit or no-limit
                Phase 6+: parquet re-walk via walk_engine