---
|   app.py
|   config.py
|   data_loader.py
|   db.py
|   requirements.txt
|   trades.db
|
+---tests
|   |   conftest.py
|   |   helpers.py
|   |   pytest.ini
|   |   test_01_basic_buy.py
|   |   test_02_sell.py
|   |   test_03_breakeven.py
|   |   test_04_wide_candle.py
|   |   test_05_untp.py
|   |   test_06_limit_orders.py
|   |   test_07_stop_orders.py
|   |   test_08_pip_sizes.py
|   |   test_09_sampling.py
|   |   test_10_streak.py
|   |   test_11_edge_cases.py
|   |   test_12_integration.py
|   |   test_13_eurusd_scenarios.py
|   |   test_14_statistics.py
|   |   __init__.py

+---AI_DOC
|       AI_CODEBASE_MAP.md
|       AI_DEBUG_GUIDE.md
|       AI_FUNCTION_MAP.md
|       Backtest_Architecture.md
|       checklist.md
|       MCP.md
|       Phases_Backtest.md
|
+---routes
|   |   channel_routes.py
|   |   save_routes.py
|   |   statistics_routes.py
|   |   __init__.py
|
+---Stored files
|       AUDCAD.parquet ... XAUUSD.parquet  (39 parquet files)
|
+---templates
|   |   channels.html
|   |   channel_detail.html
|   |   error.html
|   |   index.html
|   |   results.html
|   |   statistics.html          ← shell only (DECISION-18)
|   |
|   \---partials
|           stats_m1_overview.html     ← Phase 4/5 BUILT
|           stats_m2_hitrate.html      ← Phase 5 BUILT
|           stats_m3_sweep.html        ← Phase 6 
|           stats_m4_becompare.html    ← Phase 6 
|           stats_m5_dip.html          ← Phase 7 placeholder
|           stats_m6_strategy.html     ← Phase 7 placeholder
|           stats_m7_pnl.html          ← Phase 5 BUILT
|
+---utils
|   |   datetime_utils.py
|   |   mfe_calculator.py
|   |   pip_utils.py
|   |   symbols.py
|   |   trade_calculations.py
|   |   trade_monitor.py         ⛔ READ-ONLY
|   |   trade_statistics.py
|   |   trade_storage.py
|   |   trade_validation.py
|   |   walk_engine.py           ← Phase 6 NEW
|   |   __init__.py
|
\---__pycache__

## 1. ARCHITECTURAL LAYERS

### Flask Application Layer

`app.py` — Entry point. Registers blueprints, configures logging, owns the monitor form route and results route. No business logic — delegates immediately to utils.

### Route Layer (routes/)

Three blueprints. Each is a thin HTTP adapter: parse request → call storage/calculator/statistics → return JSON or render template.

- `routes/save_routes.py` — Trade save flow
- `routes/channel_routes.py` — Channel CRUD + trade ops
- `routes/statistics_routes.py` — Statistics hub + all statistics APIs

### Database Models Layer

`db.py` — SQLAlchemy ORM models for Channel and Trade. Defines the complete schema (250+ fields). `init_db()` is called at app startup.

### Save-Time Walk Engine (Core)

`utils/mfe_calculator.py` — The most complex save-time file. Executes both the trade walk and UNTP walk simultaneously at save time. Produces all computed fields. READ-ONLY dependency on parquet data. Never touches Flask or DB directly except via `_compute_streak()`.

### Query-Time Walk Engine (Phase 6)

`utils/walk_engine.py` — Query-time parquet re-walk engine. Used by statistics routes for candle-level MFE precision. Uses already-loaded `data_frames` dict (zero disk I/O). No DB writes. Called by: M1 fixed_untp route, M1 untp_overview route, M3 RR Sweep route, M4 BE Comparison route.

### DB Read/Write Layer

`utils/trade_storage.py` — All DB queries. No Flask. No statistics. CRUD for channels and trades, metadata aggregation, CSV export. The only file (besides routes) that imports `db`.

### Statistics Engine

`utils/trade_statistics.py` — Pure computation. No DB, no Flask. Accepts plain trade dicts. Computes all statistics modules: M1 overview, M2 hit rate, M7 PnL report. Phase 6 upgrades to use walk_engine results for fixed_untp and untp_overview.

### Validation Layer

`utils/trade_validation.py` — Monitor-time input validation for the form in `app.py`. Validates trade type, SL/TP direction, breakeven, expiry.

### Price/Pip Math Layer

`utils/trade_calculations.py` — Price lookups from parquet (used at monitor time only, not save time). Also contains `get_file_name()` for NAS100→USTEC mapping and `calculate_pips()`.

### Data Loader

`data_loader.py` — Module-level code. Preloads all 39 parquet files into `data_frames` dict at startup. Both `mfe_calculator` (save-time) and `walk_engine` (query-time) import this dict directly. No functions — pure side-effect on import.

### Utility Helpers

`utils/pip_utils.py` — Single function `get_pip_size(symbol)`. AUTHORITATIVE source for pip sizes. Never hardcode pip sizes anywhere else.
`utils/datetime_utils.py` — Datetime parsing helpers used by `app.py` at monitor time.
`utils/symbols.py` — `SYMBOLS` list (33 forex pairs + 6 instruments = 39 total).
`utils/trade_monitor.py` — ⛔ READ-ONLY. Original trade monitor engine. Never modify.

### Templates (Frontend)

`statistics.html` is a shell only — 7 partials loaded via Jinja2 `{% include %}` (DECISION-18). Each partial is self-contained with its own HTML panel + module-specific JS.

---

## 2. FILE-BY-FILE DEEP OVERVIEW

---

### FILE: app.py

**Purpose** Flask app entry point. Owns the monitor form flow. All other functionality is delegated to blueprints.

**Key Responsibilities**

- Creates Flask app, sets secret key, calls `init_db(app)`
- Registers three blueprints: `save_bp`, `channel_bp`, `stats_bp`
- Handles `GET /` → renders monitor form with symbol list
- Handles `POST /monitor_trade` → validates inputs, calls `monitor_trade()`, extracts `actual_entry_price`, builds `save_context`, renders results
- Global exception handler → `error.html`

**Important Functions** `monitor_trade_route()` — Core monitor POST handler. Validates form, calls `monitor_trade()` from `trade_monitor.py`, extracts actual_entry_price from results string (with 3-level fallback: parse results / limit_price / get_closing_price), builds `save_context` dict passed to results.html for the save modal.

**Critical Notes**

- `actual_entry_price` extraction has a 3-level fallback. If all fail, it passes `""` to results.html, and `save_routes._parse_form` will raise a clear ValueError at save time.
- Logging: INFO suppressed for app code, WARNING+ only. werkzeug stays at INFO so the server address prints.

---

### FILE: db.py

**Purpose** SQLAlchemy ORM definitions for the two database tables: `channels` and `trades`.

**Key Responsibilities**

- Defines `Channel` model (6 fields)
- Defines `Trade` model (140+ fields including 56 UNTP snapshot columns)
- `init_db(app)` configures DB URI and calls `db.create_all()`
- `Trade.to_dict()` serialises all fields to plain dict (used by statistics layer)

**Important Functions**

`init_db(app)` — Called once at startup. Sets `SQLALCHEMY_DATABASE_URI` to `trades.db` in project root.

`Trade.to_dict()` — Full serialisation of all 140+ fields to a dict. This is the only path data takes from DB into the statistics engine.

**Schema Summary**

Channel: `channel_id`, `name`, `description`, `color`, `created_at`, `is_archived`

Trade field groups:
- User-provided: symbol, trade_type, entry_time, entry_price, stoploss_price, takeprofit_price, limit_price, breakeven fields, input_type, notes, untp_notes, saved_at
- Computed TP targets: tp_rr_target, tp_pips_target
- Pending order context: pending_trigger_time, pending_wait_minutes, pending_order_triggered
- Trade walk excursion: mfe_pips/r, mfe_at_close_pips/r, mae_pips/r, sl_distance_pips, retracement fields, exit_price, candles_to_resolution, dip fields
- Outcome/P&L: outcome_at_user_tp, pnl_r, rr_at_user_tp, time_to_resolution_minutes, tp_was_reached, time_to_tp_minutes, peak_rr_at_close
- Breakeven: breakeven_triggered, breakeven_sl_price, breakeven_trigger_time_minutes, mfe_at_breakeven_pips/r, mfe_after_be_pips/r
- R milestone timing: time_to_0_5r through time_to_5r_minutes (7 fields, NULL if not reached)
- UNTP snapshots: 14 checkpoints × 4 fields = 56 columns (mfe_at_Xh_r, mae_at_Xh_r, outcome_at_X, alive_at_X)
  NOTE: Phase 6+ — used for channel detail drawer display only. Statistics uses walk_engine re-walk.
- Entry quality: first_candle_direction, consecutive_adverse_candles, avg_candle_size_pips_at_entry
- Session context: entry_day_of_week, entry_hour, entry_session
- Channel streak: channel_streak_at_save
- Integrity: price_path_captured
- UNTP path: mfe_path_json (JSON text, 15-min sampled — display use only in Phase 6+)

**Critical Notes**

- `db.create_all()` NEVER adds columns to existing tables. Any schema change = delete `trades.db` and re-run migration.
- `channel_id` on Trade has `index=True` — essential for query performance as table grows.

---

### FILE: routes/save_routes.py

**Purpose** Blueprint owning two routes: `POST /save_trade` and `GET /channels/list_json`.

**Key Responsibilities**

- Parses and validates the save form (`_parse_form`)
- Resolves or creates the target channel (`_get_or_create_channel`)
- Calls `calculate_mfe()` to run both walks and produce all computed fields
- Constructs and commits the `Trade` ORM object

**Important Functions**

`save_trade()` — Main handler. Orchestrates the full save flow in one transaction: parse → channel resolve → calculate_mfe → Trade() construction → commit.

`_parse_form(form)` — Validates required fields, parses entry_time, normalises breakeven/input_type flags.

`_get_or_create_channel(channel_id, ...)` — Handles both existing channel selection and new channel creation.

`list_channels_json()` — Lightweight GET for the save modal's channel dropdown.

**Critical Notes**

- All 140+ Trade fields are explicitly named in the constructor — no `**kwargs`.
- If `calculate_mfe` fails (price_path_captured=False), the trade is still saved with all numeric fields as None.

---

### FILE: routes/channel_routes.py

**Purpose** Blueprint for all channel management and trade operations. Thin HTTP adapter — all logic lives in `trade_storage.py`.

**Key Responsibilities**

- Channel list page with optional archived filter
- Channel CRUD: create, rename, archive, unarchive, delete (with force flag)
- Channel detail page with filter support
- Trade operations: delete, move, inline notes update, UNTP notes update
- CSV export

**Important Functions**

`channel_detail(channel_id)` — GET /channels/<id>. Loads filtered trades + calls `get_channel_detail_context()` for metadata and filter options in a single shared DB round-trip.

`update_trade_notes(trade_id)` — POST /trades/<id>/notes. AJAX TP drawer notes save.

`update_untp_notes(trade_id)` — POST /trades/<id>/untp-notes. AJAX UNTP drawer notes save. Writes to `untp_notes` column — SEPARATE from `notes`. Never mix.

**Critical Notes**

- `from db import Channel` is imported locally inside `delete_trade_route`, not at module top.
- TP notes → `Trade.notes` column. UNTP notes → `Trade.untp_notes` column. Never cross-write.

---

### FILE: routes/statistics_routes.py

**Purpose** Blueprint for all statistics APIs. Module 1 overview, Module 2 hit rate, Module 7 PnL report. Phase 6 adds sweep and becompare routes.

**Key Responsibilities**

- Renders statistics hub page with channel list, symbols, time-limit dropdown
- Accepts JSON filter payloads, loads matching trades, calls statistics engine
- Phase 6: calls walk_engine for fixed_untp and untp_overview modes

**Important Functions**

`statistics_hub()` — GET /statistics. Queries distinct symbols. Passes TIME_LIMIT_LABELS for dropdown.

`statistics_overview()` — POST /statistics/overview. Dispatches to correct compute function based on tp_mode. For fixed_untp and untp_overview: Phase 6 calls walk_engine.walk_trade_untp() per trade.

`statistics_hitrate()` — POST /statistics/hitrate. Calls compute_hit_rate(). Returns Module 2 result.

`statistics_pnl()` — POST /statistics/pnl. Calls compute_pnl_report(). Returns Module 7 result. Ignores tp_mode/unit/time_limit — uses pnl_r directly (R2).

`statistics_sweep()` — POST /statistics/sweep. Phase 6. Calls walk_engine once per trade per request. Returns path array per trade to client.

`statistics_becompare()` — POST /statistics/becompare. Phase 6. Calls walk_engine twice per trade (BE on + BE off). Returns aggregated groups.

`_load_trades(filters)` — Internal helper. Builds SQLAlchemy query from filter dict. Supports channel_ids, date range, symbol, trade_type. Orders by entry_time ASC for correct equity curve chronology.

**Mode dispatch (statistics_overview):**
- original_tp → compute_overview()
- fixed_tp → compute_overview()
- fixed_untp → Phase 4/5: compute_fixed_untp_overview() | Phase 6+: walk_engine + compute_fixed_untp_overview()
- untp_overview → Phase 4/5: compute_untp_stats() | Phase 6+: walk_engine + compute_untp_stats()

---

### FILE: utils/mfe_calculator.py

**Purpose** Core save-time analytical engine. Executes both the trade walk and UNTP walk simultaneously at save time. Produces all ~140 computed fields.

**Key Responsibilities**

- Handles pending orders (limit/stop): waits for trigger candle
- Runs trade walk: iterates M1 candles, detects TP/SL/BE in defined step order
- Runs UNTP walk simultaneously: continues past trade close for TP trades
- Records 14 checkpoint snapshots × 4 fields (56 UNTP columns)
- Samples `mfe_path_json` every 15 minutes (using `+= PATH_INTERVAL_MIN`, not `= elapsed_min`)
- Computes entry quality: first_candle_direction, consecutive_adverse_candles
- Computes session context: entry_day_of_week, entry_hour, entry_session
- Calls `_compute_streak()` for channel_streak_at_save
- Applies post-walk cleanup for phantom dip and phantom BE

**Important Functions**

`calculate_mfe(...)` — Public entry point. Called exclusively by `save_routes.save_trade()`. Returns a fully-keyed dict matching all Trade column names. On any exception returns `_empty_result()` with `price_path_captured=False`.

`_compute_streak(channel_id)` — Queries existing channel trades ORDER BY entry_time DESC. hit_tp=+1, hit_sl=-1, hit_be/open/none=skip. Returns int.

`_empty_result()` — Returns a dict with all keys set to None and price_path_captured=False.

`_classify_session(hour)` — Maps UTC hour to session string.

**Candle Iteration Order (exact — do not reorder):**
a. Update elapsed_minutes
b. Update R milestones
c. Dip check
d. BE trigger check
e. SL check (original SL, or entry_price if BE triggered)
f. TP check
g. UNTP snapshot recording

**Post-Walk Cleanup (AFTER loop, not inside):**
- Dip phantom: if `peak_dip_time >= resolution_candle_time` → zero all dip fields
- BE phantom: if `outcome == 'hit_tp' AND be_trigger_min == resolution_min` → clear all BE fields

**Constants**
```
CHECKPOINT_MINUTES = [30, 60, 120, 240, 480, 720, 1440, 2880, 4320, 7200, 10080, 14400, 20160, 30240]
CHECKPOINT_KEYS    = ["30min", "1h", "2h", "4h", "8h", "12h", "24h", "48h", "72h", "120h", "168h", "240h", "336h", "504h"]
UNTP_CAP_MINUTES   = 30240
PATH_INTERVAL_MIN  = 15
```

**Critical Notes**

- UNTP MFE/MAE is frozen at stop — `untp_mfe_frozen` captures peak. All remaining checkpoints backfilled with alive=False immediately.
- `mfe_after_be_r` measures trade walk only: from BE activation to TRADE CLOSE, not UNTP stop.
- UNTP stop condition depends on `be_triggered` ACTUAL flag, not `breakeven_active` config.
- sell dip: measured as price ABOVE entry (not below).
- Phase 6 note: mfe_calculator is save-time only. walk_engine.py is the query-time equivalent.

---

### FILE: utils/walk_engine.py  ← Phase 6 NEW

**Purpose** Query-time parquet re-walk engine. Produces candle-level MFE/MAE/path data for statistics. Used by statistics routes — never at save time. No DB writes.

**Key Responsibilities**

- Walks parquet candles from trade entry to natural stop or time cap
- Supports two BE modes: active (user-supplied trigger R) or inactive (SL only)
- Returns per-trade: peak_mfe_r, peak_mae_r, stop_reason, stopped_at_min, path
- Raises WalkDataError when entry candle not found in parquet

**Important Functions**

`walk_trade_untp(trade, data_frames, max_minutes, be_active, be_trigger_r) → dict`

Parameters:
- `trade` — trade dict from Trade.to_dict()
- `data_frames` — already-loaded parquet dict from data_loader (zero disk I/O)
- `max_minutes` — walk cap; use 30240 for "no limit" (504h)
- `be_active` — True = apply BE at be_trigger_r; False = walk to SL only
- `be_trigger_r` — user-supplied R level for BE trigger; only used when be_active=True

Returns:
```python
{
  'peak_mfe_r':     float,
  'peak_mae_r':     float,
  'stop_reason':    str,       # 'sl' | 'be' | 'time_limit' | 'open'
  'stopped_at_min': int|None,
  'path':           list       # [[elapsed_min, mfe_r, mae_r], ...]
}
```

Stop reason semantics:
- `'sl'` — original SL hit → SL bucket in untp_overview
- `'be'` — BE triggered at be_trigger_r then price retraced to entry → BE bucket
- `'time_limit'` — max_minutes reached → Open bucket
- `'open'` — parquet data exhausted before any stop → Open bucket

**BE rules (DECISION-22):**
- be_active=True: trigger BE when price hits be_trigger_r in favour. Stop at entry retrace.
  Trade's breakeven_active / breakeven_value / breakeven_type are NEVER read.
- be_active=False: walk to original SL only. stop_reason never 'be'.

**Error handling:**
- `WalkDataError` raised if entry candle not found in parquet
- Caller catches, excludes trade, adds to excluded_count

**Inputs** Called by: statistics_routes (M1 upgrade, sweep, becompare)
Uses: `data_loader.data_frames` (pre-loaded), `pip_utils.get_pip_size()`
Never touches: DB, Flask, mfe_calculator

**Critical Notes**

- Both BE on/off walks are always fresh from entry candle. Original trade's BE state is completely irrelevant.
- Open trades walk to parquet end, capped at 504h.
- Same candle iteration order as mfe_calculator: a→g.

---

### FILE: utils/trade_storage.py

**Purpose** All database read/write operations. No Flask, no statistics, no walk logic.

**Key Responsibilities**

- Channel CRUD: get, create, rename, archive, unarchive, delete
- Trade queries: by channel (with filters), by id
- Trade operations: delete, move (with streak recalculation)
- Metadata aggregation for channel list and channel detail pages
- CSV export (all 56 UNTP columns + mfe_path_json included — P2-GAP-1 CLOSED)

**Important Functions**

`get_all_channel_metas(include_archived)` — Optimised O(2) bulk query: one channel query + one bulk Trade IN query. Groups in Python to avoid N+1 queries.

`get_channel_detail_context(channel_id)` — Loads ALL trades for channel once, derives both meta and filter_options from that single list.

`get_trades_by_channel(...)` — Filtered Trade query. Orders by entry_time DESC.

`delete_trade(trade_id)` — Captures `channel_id` as plain int BEFORE commit to avoid DetachedInstanceError.

`move_trade(trade_id, new_channel_id)` — Calls `_recompute_channel_streaks()` for both source and destination channels after move (P2-GAP-2 CLOSED).

`export_trades_csv(...)` — Produces CSV via `_CSV_COLUMNS`. All 56 UNTP columns + mfe_path_json included (P2-GAP-1 CLOSED 2026-03-15).

---

### FILE: utils/trade_statistics.py

**Purpose** Pure computation layer. No DB, no Flask. Accepts trade dicts (from `Trade.to_dict()`), returns result dicts. All statistics modules.

**Key Responsibilities**

- Resolves each trade as win/loss/inconclusive for original_tp and fixed_tp modes
- Computes UNTP overview metrics (fixed_untp, untp_overview) using stored snapshots (Phase 4/5)
  Phase 6: these functions receive walk_engine results instead of stored columns
- Builds equity curve, drawdown curve, streaks, EV for Module 1
- Hit rate breakdowns by symbol/session/trade_type/day-of-week for Module 2
- Equity curve, weekly/monthly totals, per-symbol breakdown, streaks for Module 7

**Important Functions**

`resolve_win_loss(trade, tp_mode, tp_value, time_limit_hours, unit)` — Classifier for original_tp and fixed_tp only. Returns 'win'|'loss'|'inconclusive'.

`compute_overview(trades, tp_mode, tp_value, time_limit_hours, unit)` — Module 1 entry point for original_tp and fixed_tp. Returns result_type='overview'.

`compute_fixed_untp_overview(trades, tp_value, time_limit_hours, unit)` — Module 1 for fixed_untp mode. Win = peak_mfe_r >= target. Returns result_type='overview'. Phase 6: receives walk_engine peak_mfe_r instead of stored mfe_at_Xh_r.

`compute_untp_stats(trades, time_limit_hours, tp_mode, tp_value, unit)` — Module 1 for untp_overview mode. Returns three groups (stats_all, stats_be_active, stats_no_be) for client-side BE toggle. Phase 6: groups replaced by stats_be_on / stats_be_off from walk_engine results.

`compute_hit_rate(trades, tp_mode, tp_value, time_limit_hours, unit)` — Module 2. Breakdown by symbol, trade_type, session, day_of_week. All 4 modes supported. Returns result_type='hitrate'.

`compute_pnl_report(trades)` — Module 7. Uses pnl_r directly (R2 — mode agnostic). Equity curve, weekly/monthly totals, per-symbol, streaks.

`_classify_for_hitrate(trade, tp_mode, ...)` — Per-trade classifier for Module 2 rows.

`_build_hitrate_rows(groups, ...)` — Builds one dimension's row list from {label: [trades]} dict.

`_get_snapshot_cols(time_limit_hours)` — Maps time limit float to (mfe_col, alive_col) tuple.

`_get_mae_col(time_limit_hours)` — Maps time limit float to mae column name.

**Critical Notes**

- fixed_untp win rule (BUG-16, DECISION-22): win = peak_mfe >= target; alive is IRRELEVANT.
  Phase 4/5: uses stored mfe_at_Xh_r. Phase 6+: uses walk_engine peak_mfe_r. Same rule.
- PnL report (compute_pnl_report): ignores tp_mode entirely. Uses pnl_r directly. R2.
- hit_be = LOSS in original_tp mode win rate. hit_be = SKIP in streak. These are different.
- price_path_captured=False trades excluded from ALL statistics.

---

### FILE: utils/trade_validation.py

**Purpose** Monitor-time input validation. Used by `app.py` for `/monitor_trade` POST.

`validate_trade_type(form_data)` — Extracts and validates trade_type.

`process_trade_inputs(request, trade_type, entry_time, get_closing_price_func, symbol)` — Master input processor. Returns `(limit_price, stoploss_price, takeprofit_price, input_type)`.

`validate_breakeven_input(request)` — Returns `(breakeven_bool, breakeven_type, breakeven_value)`.

`validate_expiry_input(request, trade_type)` — Returns `(expiry_enabled, days, hours, minutes)`.

**Note**: Validates monitor-time inputs only. Save-time validation is in `save_routes._parse_form()`.

---

### FILE: utils/trade_calculations.py

**Purpose** Price lookups and pip math. Used at monitor time by `app.py`.

`get_closing_price(year, month, day, hour, minute, symbol)` — Loads parquet, finds close price at timestamp.

`get_file_name(symbol)` — Applies FILE_NAME_MAPPING (NAS100→USTEC). Used by data_loader.py.

`calculate_pips(entry_price, target_price, symbol)` — Pip distance. Has own pip logic — always prefer `pip_utils.get_pip_size()` for authoritative values.

**Note**: Reads parquet directly on each call (no caching). Save-time uses pre-loaded `data_frames`.

---

### FILE: utils/pip_utils.py

**Purpose** Single authoritative source for pip sizes.

`get_pip_size(symbol)` — XAUUSD=0.1, XAGUSD=0.01, NAS100/US30=1.0, USOIL/UKOIL=0.1, JPY=0.01, others=0.0001.

**Critical Rule** NEVER hardcode pip sizes. The local fallback in `mfe_calculator.py` must stay in sync.

---

### FILE: data_loader.py

**Purpose** Module-level startup code. Loads all 39 parquet files into `data_frames` dict at startup.

- Iterates SYMBOLS, resolves filename via `get_file_name()`, loads each parquet
- Parses `Local time` column with format `%d.%m.%Y %H:%M:%S`
- Stores each DataFrame in `data_frames[symbol.upper()]`

**Critical Notes**

- Keys are uppercase symbol strings. Key for NAS100 is `"NAS100"` (not "USTEC").
- Both `mfe_calculator` (save-time) and `walk_engine` (query-time) import `data_frames` directly.
- Any symbol not loaded simply won't have an entry — both engines handle this gracefully.

---

### FILE: utils/symbols.py

`SYMBOLS` — List of 39 symbols. Used by `app.py` for monitor form and by `data_loader.py`.

---

### FILE: utils/datetime_utils.py

`validate_datetime_input(form)` — Parses and validates entry_date + entry_time from monitor form.

---

### FILE: utils/trade_monitor.py ⛔ READ-ONLY

**Critical Rule** NEVER modify this file. Called by `app.py` via `monitor_trade(...)`. Output displayed to user before they decide to save.

---

## 3. CROSS-FILE DEPENDENCY MAP

```
Browser (form POST)
        │
        ▼
app.py
  GET /  → renders index.html (SYMBOLS list)
  POST /monitor_trade
    → datetime_utils.validate_datetime_input()
    → trade_validation.validate_trade_type()
    → trade_validation.process_trade_inputs()
         └── trade_calculations.get_closing_price()  ← reads parquet directly
         └── pip_utils.get_pip_size()
    → trade_monitor.monitor_trade()  [READ-ONLY]
    → renders results.html (with save_context)

routes/save_routes.py  (save_bp)
  POST /save_trade
  → _parse_form()
  → _get_or_create_channel()  ← db.Channel
  → mfe_calculator.calculate_mfe()
       └── data_loader.data_frames  ← pre-loaded parquets
       └── pip_utils.get_pip_size()
       └── db.Trade (streak query only via _compute_streak())
  → db.Trade(...)
  → db.session.commit()
  → returns JSON

  GET /channels/list_json
  → db.Channel.query

routes/channel_routes.py  (channel_bp)
  All channel + trade routes
  → trade_storage.*  ← ALL DB logic lives here
       └── db.Channel, db.Trade

routes/statistics_routes.py  (stats_bp)
  POST /statistics/overview (original_tp / fixed_tp)
  → _load_trades()  ← db.Trade.query
  → trade.to_dict() for each
  → trade_statistics.compute_overview()
       └── trade_statistics.resolve_win_loss()
  → returns JSON

  POST /statistics/overview (fixed_untp / untp_overview) — Phase 6+
  → _load_trades()
  → walk_engine.walk_trade_untp() × 2 per trade (BE on + BE off)
       └── data_loader.data_frames  ← zero disk I/O
       └── pip_utils.get_pip_size()
  → trade_statistics.compute_fixed_untp_overview() or compute_untp_stats()
  → returns JSON with stats_be_on + stats_be_off

  POST /statistics/hitrate
  → _load_trades()
  → trade_statistics.compute_hit_rate()
  → returns JSON

  POST /statistics/pnl
  → _load_trades()
  → trade_statistics.compute_pnl_report()
  → returns JSON

  POST /statistics/sweep  (Phase 6)
  → _load_trades()
  → walk_engine.walk_trade_untp() × 1 per trade (one BE mode per request)
  → returns path array per trade as JSON

  POST /statistics/becompare  (Phase 6)
  → _load_trades()
  → walk_engine.walk_trade_untp() × 2 per trade (BE on + BE off)
  → returns aggregated group comparison as JSON

data_loader.py
  (module-level, runs at import)
  → symbols.SYMBOLS
  → trade_calculations.get_file_name()
  → pd.read_parquet("Stored files/{symbol}.parquet")
  → populates data_frames dict

utils/walk_engine.py  (Phase 6)
  → data_loader.data_frames  (imported directly)
  → pip_utils.get_pip_size()
  (no Flask, no DB, no mfe_calculator)

utils/trade_storage.py
  → db.Channel, db.Trade only
  (no Flask, no statistics, no walk logic)

utils/trade_statistics.py
  → accepts plain dicts only
  (no Flask, no DB, no parquet)

utils/pip_utils.py
  → standalone (no imports)
```

---

## 4. CRITICAL LOGIC LOCATIONS

| Topic | File | Function/Section |
|---|---|---|
| Save-time trade walk | `utils/mfe_calculator.py` | `calculate_mfe()` — main candle loop |
| Save-time UNTP walk + snapshots | `utils/mfe_calculator.py` | Inside same candle loop as trade walk |
| Post-walk cleanup (dip + BE phantoms) | `utils/mfe_calculator.py` | After loop, before building result dict |
| Streak computation | `utils/mfe_calculator.py` | `_compute_streak()` |
| mfe_path_json sampling | `utils/mfe_calculator.py` | PATH_INTERVAL_MIN += logic |
| pnl_r assignment | `utils/mfe_calculator.py` | Section 9 "Derive outcome / pnl_r" |
| Query-time UNTP re-walk | `utils/walk_engine.py` | `walk_trade_untp()` |
| Win/loss classification (original_tp, fixed_tp) | `utils/trade_statistics.py` | `resolve_win_loss()` |
| fixed_untp classification | `utils/trade_statistics.py` | `compute_fixed_untp_overview()` |
| untp_overview bucketing | `utils/trade_statistics.py` | `compute_untp_stats()` |
| Module 1 overview stats | `utils/trade_statistics.py` | `compute_overview()` |
| Module 2 hit rate | `utils/trade_statistics.py` | `compute_hit_rate()` |
| Module 7 PnL report | `utils/trade_statistics.py` | `compute_pnl_report()` |
| Database schema | `db.py` | `Trade` model |
| Trade serialisation | `db.py` | `Trade.to_dict()` |
| Save flow orchestration | `routes/save_routes.py` | `save_trade()` |
| Statistics routes dispatch | `routes/statistics_routes.py` | `statistics_overview()`, `_load_trades()` |
| Monitor form processing | `app.py` | `monitor_trade_route()` |
| Channel CRUD | `utils/trade_storage.py` | `create_channel`, `delete_channel`, etc. |
| Channel metadata (list page) | `utils/trade_storage.py` | `get_all_channel_metas()` |
| Channel detail context | `utils/trade_storage.py` | `get_channel_detail_context()` |
| CSV export | `utils/trade_storage.py` | `export_trades_csv()` / `_CSV_COLUMNS` |
| Pip sizes | `utils/pip_utils.py` | `get_pip_size()` |
| Parquet data loading | `data_loader.py` | Module-level loop → `data_frames` |
| Symbol→filename mapping (NAS100) | `utils/trade_calculations.py` | `FILE_NAME_MAPPING`, `get_file_name()` |
| Input validation (monitor) | `utils/trade_validation.py` | `process_trade_inputs()` |
| Input validation (save) | `routes/save_routes.py` | `_parse_form()` |
| Trade detail drawer JS | `templates/channel_detail.html` | `renderDrawerContent()` |
| UNTP drawer JS | `templates/channel_detail.html` | `openUntpDrawer()`, `renderUntpDrawerContent()` |
| RR/Pips toggle | `templates/channel_detail.html` | `show-pips` class on `<body>` (CSS-driven) |
| Statistics Module 1 UI | `templates/partials/stats_m1_overview.html` | `renderOverview()`, `renderUntpStats()` |
| Statistics Module 2 UI | `templates/partials/stats_m2_hitrate.html` | `renderHitRate()` |
| Statistics Module 7 UI | `templates/partials/stats_m7_pnl.html` | `renderPnlReport()` |
| Statistics Module 3 UI (Phase 6) | `templates/partials/stats_m3_sweep.html` | — |
| Statistics Module 4 UI (Phase 6) | `templates/partials/stats_m4_becompare.html` | — |

---

## 5. ROUTE MAP

```
GET  /
     → app.py :: index()
     Renders: index.html with SYMBOLS list for monitor form

POST /monitor_trade
     → app.py :: monitor_trade_route()
     Validates inputs, runs monitor, renders results.html with save_context

POST /save_trade
     → routes/save_routes.py :: save_trade()
     Runs mfe_calculator, saves Trade to DB. Returns JSON.

GET  /channels/list_json
     → routes/save_routes.py :: list_channels_json()
     Returns JSON array of non-archived channels for save modal dropdown.

GET  /channels
     → routes/channel_routes.py :: channels_list()
     Renders channel list page. Optional ?archived=1 to include archived.

POST /channels/create
     → routes/channel_routes.py :: create_channel_route()

POST /channels/<id>/rename
     → routes/channel_routes.py :: rename_channel_route()

POST /channels/<id>/archive
     → routes/channel_routes.py :: archive_channel_route()

POST /channels/<id>/unarchive
     → routes/channel_routes.py :: unarchive_channel_route()

POST /channels/<id>/delete
     → routes/channel_routes.py :: delete_channel_route()
     Accepts force=true/1/yes to delete with trades.

GET  /channels/<id>
     → routes/channel_routes.py :: channel_detail()
     Renders channel detail page with filtered trades table.
     Query params: symbol, trade_type, outcome, date_from, date_to

GET  /channels/<id>/export
     → routes/channel_routes.py :: export_channel_csv()
     Streams CSV download. Includes all 56 UNTP columns + mfe_path_json.

POST /trades/<id>/delete
     → routes/channel_routes.py :: delete_trade_route()

POST /trades/<id>/move
     → routes/channel_routes.py :: move_trade_route()

POST /trades/<id>/notes
     → routes/channel_routes.py :: update_trade_notes()
     AJAX TP drawer notes. Writes to Trade.notes column.

POST /trades/<id>/untp-notes
     → routes/channel_routes.py :: update_untp_notes()
     AJAX UNTP drawer notes. Writes to Trade.untp_notes column. SEPARATE from notes.

GET  /statistics
     → routes/statistics_routes.py :: statistics_hub()
     Renders statistics hub with channel list, symbol list, time-limit options.

POST /statistics/overview
     → routes/statistics_routes.py :: statistics_overview()
     Accepts JSON filter, returns Module 1 result.
     Phase 6: fixed_untp and untp_overview use walk_engine re-walk.
     Body: {channel_ids, date_from, date_to, symbol, trade_type,
            tp_mode, tp_value, unit, time_limit_hours,
            be_active, be_trigger_r}  ← be fields added Phase 6

POST /statistics/symbols
     → routes/statistics_routes.py :: statistics_symbols()
     Returns distinct symbols for given channel_ids.

POST /statistics/hitrate
     → routes/statistics_routes.py :: statistics_hitrate()
     Module 2 hit rate breakdown. Returns result_type='hitrate'.

POST /statistics/pnl
     → routes/statistics_routes.py :: statistics_pnl()
     Module 7 PnL report. Ignores tp_mode — uses pnl_r directly.

POST /statistics/sweep                    ← Phase 6
     → routes/statistics_routes.py :: statistics_sweep()
     M3 RR Sweep. Returns path per trade for client-side sweep calculation.
     Body: {channel_ids, date_from, date_to, symbol, trade_type,
            be_active, be_trigger_r, max_minutes}

POST /statistics/becompare               ← Phase 6
     → routes/statistics_routes.py :: statistics_becompare()
     M4 BE Comparison. Returns aggregated BE on/off groups.
     Body: {channel_ids, date_from, date_to, symbol, trade_type,
            be_trigger_r, max_minutes}
```

---

## 6. TEMPLATE OVERVIEW

---

### templates/index.html

**Purpose** Trade monitor form.

**Key Features**
- Symbol selector, trade type selector, entry time, SL/TP in three modes
- Breakeven settings, pending order expiry fields

---

### templates/results.html

**Purpose** Displays monitor output. Contains Save Trade button/modal.

**Key Features**
- Results list (plain text from trade_monitor)
- Save modal: channel dropdown, optional notes, new channel creation
- Handles `price_path_captured: false` response with warning toast

---

### templates/channels.html

**Purpose** Channel list page.

**Key Features**
- Channel cards with trade count, win rate, net R
- Create channel modal, rename/archive/delete per card

---

### templates/channel_detail.html

**Purpose** Most complex template. Filtered trades table, TP drawer, UNTP section, UNTP drawer.

**Key Features**
- Filter bar, trades table, TP trade detail drawer
- UNTP view toggle: switches between TP table and UNTP section
- UNTP window selector: 14-checkpoint slider + numeric input
- RR/Pips toggle: pill button adds `show-pips` to `<body>` (CSS-driven — no JS re-render)
- Trade Analysis Section in TP drawer: shape, MFE:MAE, MFE Utilisation, Exit Efficiency, MAE Pressure
- UNTP drawer (#untpDrawer): separate element, independent Escape/overlay handlers

**Important JS Functions**

`renderDrawerContent(trade)` — Renders full TP drawer HTML. CRITICAL TDZ-sensitive const order:
1. DAYS, streakVal, _outcome
2. _streakIsNeutral, streakDisplay
3. ref, _refMfe, _refMae, _refStopped
4. _dip, _advCandles
5. shapeName (+ shape vars)
6. metrics block
7. refLabel
8. innerHTML assignment

`renderUntpDrawerContent(trade)` — Renders UNTP drawer HTML.

`classifyUntpTrade(trade, window)` — Buckets trade as running/sl/be. alive=true → Running ALWAYS regardless of MFE sign.

`resolveUntpAtWindow(trade, targetMins)` — Resolves MFE/MAE at arbitrary minute. Priority: exact CP → mfe_path_json walk → nearest CP fallback.

`untpPeakMfe(trade)` — Highest mfe_at_Xh_r where alive=True across all 14 CPs + mfe_path_json.

**Critical Notes**
- TDZ: scan renderDrawerContent in full before adding any const. Forward references crash at runtime.
- RR/Pips toggle is CSS-driven via `show-pips` body class. Never implement in JS.
- MFE:MAE denominator: hit_tp → t.mae_r; hit_sl/hit_be → _refMae.
- #untpDrawer is completely separate from #tradeDrawer.

---

### templates/statistics.html

**Purpose** Statistics hub shell only (DECISION-18). Contains: nav, sidebar, shared CSS/JS, 7 `{% include %}` partials.

**Shell responsibilities** — do NOT add module HTML or JS here:
- Filter sidebar: channel multi-select, date range, symbol, trade type, TP mode, TP value, unit toggle, time limit, BE settings
- `runStatistics()` — fires all fetch calls in parallel via Promise.all
- `buildPayload()` — builds JSON payload from sidebar inputs
- `renderChart()` — shared Chart.js helper
- Tab button activation via `switchTab()`

**Partials (self-contained HTML + JS):**
- `stats_m1_overview.html` — M1 panel, `renderOverview()`, `renderUntpStats()`
- `stats_m2_hitrate.html` — M2 panel, `renderHitRate()`
- `stats_m3_sweep.html` — M3 RR Sweep (Phase 6)
- `stats_m4_becompare.html` — M4 BE Compare (Phase 6)
- `stats_m5_dip.html` — M5 Dip (Phase 7 — placeholder)
- `stats_m6_strategy.html` — M6 Strategy Card (Phase 7 — placeholder)
- `stats_m7_pnl.html` — M7 panel, `renderPnlReport()`

---

### templates/error.html

**Purpose** Global error page. Displays error message and optional traceback.

---

## 7. DATA FLOW — FULL TRADE LIFECYCLE

```
Step 1: Monitor
  User fills index.html form → POST /monitor_trade
  → app.py validates inputs via trade_validation.py
  → app.py calls datetime_utils to parse entry_time
  → app.py calls trade_calculations.get_closing_price() to get market price
  → app.py calls trade_monitor.monitor_trade() [READ-ONLY]
  → trade_monitor walks parquet, produces plain-text result lines
  → app.py extracts actual_entry_price from result lines (3-level fallback)
  → app.py builds save_context dict
  → renders results.html with result lines + save_context

Step 2: Save Decision
  User reviews results.html
  → Clicks "💾 Save Trade" → modal opens
  → JS fetches /channels/list_json for dropdown
  → User selects channel (or creates new), optionally adds notes
  → JS POSTs to /save_trade

Step 3: Save + Walk
  POST /save_trade → routes/save_routes.py
  → _parse_form() validates and normalises form data
  → _get_or_create_channel() resolves or creates Channel
  → mfe_calculator.calculate_mfe() runs:
      a. Checks data_frames for symbol (returns _empty_result if missing)
      b. For pending orders: walks candles to find trigger
      c. FROM ENTRY CANDLE: iterates M1 candles
         Per candle, in order: elapsed → R milestones → dip → BE → SL → TP → UNTP snapshot
      d. UNTP walk continues past trade close for hit_tp
      e. Samples mfe_path_json every 15 minutes (last_path_min += 15)
      f. POST-LOOP CLEANUP: dip phantom, BE phantom
      g. Derives outcome/pnl_r/retracement
      h. Calls _compute_streak(channel_id)
      i. Classifies entry_session, entry_day_of_week, entry_hour
      j. Returns 140-key result dict
  → Trade() constructed with all fields
  → db.session.commit()
  → Returns JSON {success, trade_id, price_path_captured}

Step 4: Channel View
  User navigates to /channels/<id>
  → channel_routes.channel_detail() loads filtered trades
  → renders channel_detail.html
  → JS populates trades table from Jinja context
  → User clicks row → renderDrawerContent(trade) renders full analytics

Step 5: Statistics (Phase 4/5 — stored columns)
  User navigates to /statistics
  → User sets filters, clicks compute
  → JS POSTs to /statistics/overview (and /hitrate, /pnl in parallel)
  → statistics_overview() loads trades, calls trade.to_dict() for each
  → compute_overview() or compute_fixed_untp_overview() classifies each trade
  → Returns JSON result dict

Step 6: Statistics (Phase 6 — parquet re-walk)
  Same flow as Step 5 for original_tp and fixed_tp.
  For fixed_untp and untp_overview:
  → statistics_overview() loads trades
  → calls walk_engine.walk_trade_untp() twice per trade (BE on + BE off)
       using already-loaded data_frames (zero disk I/O)
  → passes walk results to compute_fixed_untp_overview() or compute_untp_stats()
  → Returns stats_be_on + stats_be_off groups

  For /statistics/sweep:
  → calls walk_engine once per trade (one BE mode per request)
  → returns raw path arrays to client for client-side sweep calculation

  For /statistics/becompare:
  → calls walk_engine twice per trade
  → returns aggregated BE on / BE off comparison
```

---

## 8. HOW TO FIND LOGIC IN THIS PROJECT

**Modify save-time trade walk or UNTP walk logic** → `utils/mfe_calculator.py` — `calculate_mfe()` main loop

**Modify candle iteration order** → `utils/mfe_calculator.py` — comment blocks labelled a–g inside the candle loop

**Modify post-walk cleanup (dip phantom, BE phantom)** → `utils/mfe_calculator.py` — section after the loop

**Modify streak calculation** → `utils/mfe_calculator.py` — `_compute_streak()`
→ RULE: hit_be = skip. hit_sl = -1 only. ORDER BY entry_time DESC.

**Modify pnl_r assignment** → `utils/mfe_calculator.py` — Section 9 "Derive outcome / pnl_r"
→ RULE: pnl_r is ONLY set here. Never elsewhere.

**Modify query-time re-walk engine** → `utils/walk_engine.py` — `walk_trade_untp()`
→ RULE: be_trigger_r is always user-supplied. Never read trade.breakeven_active/value.

**Modify pip sizes** → `utils/pip_utils.py` — `get_pip_size()`
→ Also update local fallback in `utils/mfe_calculator.py` and `utils/walk_engine.py` to match

**Modify trade save flow** → `routes/save_routes.py` — `save_trade()` and `_parse_form()`

**Modify channel CRUD** → `utils/trade_storage.py` — channel functions
→ `routes/channel_routes.py` — HTTP handlers (thin wrappers)

**Modify channel detail page** → `routes/channel_routes.py` — `channel_detail()` for data
→ `utils/trade_storage.py` — `get_trades_by_channel()`, `get_channel_detail_context()`
→ `templates/channel_detail.html` — all UI and JS

**Add a const to renderDrawerContent() in channel_detail.html** → scan the FULL function first
→ Follow strict declaration order (see Section 6 above)

**Modify Module 1 statistics (original_tp / fixed_tp)** → `utils/trade_statistics.py` — `compute_overview()`, `resolve_win_loss()`

**Modify Module 1 statistics (fixed_untp)** → `utils/trade_statistics.py` — `compute_fixed_untp_overview()`
→ Phase 6+: also `utils/walk_engine.py` — `walk_trade_untp()`

**Modify Module 1 statistics (untp_overview)** → `utils/trade_statistics.py` — `compute_untp_stats()`
→ Phase 6+: also `utils/walk_engine.py` — `walk_trade_untp()`

**Modify Module 2 hit rate** → `utils/trade_statistics.py` — `compute_hit_rate()`, `_classify_for_hitrate()`, `_build_hitrate_rows()`
→ UI: `templates/partials/stats_m2_hitrate.html` — `renderHitRate()`

**Modify Module 7 PnL report** → `utils/trade_statistics.py` — `compute_pnl_report()`
→ UI: `templates/partials/stats_m7_pnl.html` — `renderPnlReport()`

**Modify Module 3 RR Sweep (Phase 6)** → `routes/statistics_routes.py` — `statistics_sweep()`
→ `utils/walk_engine.py` — `walk_trade_untp()`
→ UI: `templates/partials/stats_m3_sweep.html`

**Modify Module 4 BE Comparison (Phase 6)** → `routes/statistics_routes.py` — `statistics_becompare()`
→ `utils/walk_engine.py` — `walk_trade_untp()`
→ UI: `templates/partials/stats_m4_becompare.html`

**Modify statistics routes / filters** → `routes/statistics_routes.py` — `_load_trades()`

**Modify statistics shell (sidebar, shared JS)** → `templates/statistics.html` — ONLY if sidebar filters or shared infrastructure changes. Never add module HTML/JS here.

**Add a new statistics module** → create new `templates/partials/stats_mX_name.html`
→ Add one str_replace to `statistics.html` to enable the tab button — nothing else.

**Modify database schema** → `db.py` — Trade or Channel model
→ After change: delete `trades.db` and run migration
→ Update `Trade.to_dict()` if new field needs to be in statistics
→ Update `routes/save_routes.py` Trade() constructor
→ Update `utils/mfe_calculator.py` `_empty_result()` + result dict

**Check parquet data loading** → `data_loader.py` — module-level loop
→ `data_frames` dict: keys are uppercase symbol strings

**Check NAS100 filename mapping** → `utils/trade_calculations.py` — `FILE_NAME_MAPPING = {"NAS100": "USTEC"}`

---

## 9. KNOWN ISSUES AND ACTIVE BLOCKERS

| ID | Severity | Location | Description |
|---|---|---|---|
| ST19 | Low | `statistics.html` | "Limit Buy" trade type filter — not yet manually verified with real trades |
| SR1–SR28 | Low | `statistics.html` + routes | Phase 4 statistics redesign mode checks — not yet manually verified |

**All previously listed issues CLOSED:**
- PENDING-1: DB migration complete 2026-03-14
- P2-GAP-1: _CSV_COLUMNS fixed 2026-03-15 (BUG-17) — all 56 UNTP columns present
- P2-GAP-2: move_trade() streak recalc confirmed working 2026-03-14
- P4-GAP-1: /statistics page confirmed clean 2026-03-14

**DB Migration Command**

```
python3 -c "from app import app; from db import db; app.app_context().push(); db.drop_all(); db.create_all(); print('Done')"
```

---

## 10. PERMANENT RULES

| Rule | Location | Constraint |
|---|---|---|
| hit_be = SKIP in streak | `mfe_calculator._compute_streak()` | Never treat hit_be as a loss in streak |
| Streak ORDER BY entry_time DESC | `mfe_calculator._compute_streak()` | Never order by saved_at |
| mfe_path uses `+= 15`, not `= elapsed` | `mfe_calculator` path sampling | = elapsed_min causes drift |
| Post-walk cleanup required | `mfe_calculator` after loop | Dip + BE phantoms on wide-candle TP |
| MFE:MAE denominator = t.mae_r for hit_tp | `channel_detail.html` | Never use UNTP MAE for this ratio |
| MAE Pressure = t.mae_r only | `channel_detail.html` | Not UNTP MAE |
| JS const order in renderDrawerContent | `channel_detail.html` | TDZ — scan full function first |
| db.create_all() never adds columns | Schema changes | Must delete trades.db |
| hit_be = LOSS in statistics win-rate (original_tp) | `trade_statistics.resolve_win_loss()` | original_tp mode only |
| fixed_untp win = peak_mfe >= target; alive irrelevant | `trade_statistics`, `walk_engine` | BUG-16, DECISION-22 |
| walk_engine BE uses user-supplied be_trigger_r only | `utils/walk_engine.py` | Never read trade.breakeven_active/value |
| pnl_r is the ONLY P&L field | everywhere | Never derive from MFE or outcome strings |
| statistics.html shell frozen | `templates/statistics.html` | Never add module HTML/JS to shell. New module = new partial only |
| UNTP notes → untp_notes column; TP notes → notes column | `channel_routes.py`, `db.py` | Never cross-write |
| trade_monitor.py READ-ONLY | `utils/trade_monitor.py` | Never modify |