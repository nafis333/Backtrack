# AI_FUNCTION_MAP.md
# Backtrack — Function-Level Navigation Map
# Last updated: 2026-03-13
# Purpose: Search index for every important function. Find the exact implementation without scanning files.

---

## SECTION 1 — FUNCTION DIRECTORY (grouped by file)

---

### app.py

```
index()
  Route: GET /
  Renders index.html with SYMBOLS list for the monitor form.
  No business logic — pure template render.

monitor_trade_route()
  Route: POST /monitor_trade
  Orchestrates the full monitor flow:
    1. Calls validate_datetime_input() for entry time
    2. Calls validate_trade_type() and process_trade_inputs() for SL/TP/price
    3. Calls validate_breakeven_input() and validate_expiry_input()
    4. Calls trade_monitor.monitor_trade() [READ-ONLY]
    5. Extracts actual_entry_price from result lines (3-level fallback)
    6. Builds save_context dict
    7. Renders results.html
  Entry price fallback chain:
    Level 1: parse "Entry Price:" line from results
    Level 2: use limit_price directly (pending orders)
    Level 3: re-call get_closing_price (market orders)

handle_exception(e)
  Global error handler registered with @app.errorhandler(Exception).
  Formats traceback and renders error.html with HTTP 500.

favicon()
  Route: GET /favicon.ico
  Returns favicon if static/favicon.ico exists, else 204.
```

---

### config.py

```
SECRET_KEY
  Module-level string constant. Not a function.
  Imported by app.py for Flask session security.
  Only file that should import this.
```

---

### db.py

```
init_db(app)
  Configures SQLALCHEMY_DATABASE_URI to trades.db in project root.
  Sets SQLALCHEMY_TRACK_MODIFICATIONS=False.
  Calls db.create_all() within app context.
  Called once at startup by app.py.
  WARNING: create_all() does NOT add columns to existing tables.

Channel (class)
  ORM model. Table: channels.
  Fields: channel_id (PK), name, description, color, created_at, is_archived.
  Relationship: trades (cascade="all, delete-orphan") — safety backstop.
  __repr__: returns channel name.

Trade (class)
  ORM model. Table: trades. ~140 columns.
  Field groups:
    User-provided:       symbol, trade_type, entry_time, entry_price, stoploss_price,
                         takeprofit_price, limit_price, breakeven fields, input_type,
                         notes, untp_notes, saved_at
    Computed TP targets: tp_rr_target, tp_pips_target
    Pending order:       pending_trigger_time, pending_wait_minutes, pending_order_triggered
    Trade walk:          mfe_pips/r, mae_pips/r, sl_distance_pips, exit_price,
                         retracement fields, dip fields, candles_to_resolution
    Outcome/P&L:         outcome_at_user_tp, pnl_r, rr_at_user_tp,
                         time_to_resolution_minutes, tp_was_reached, time_to_tp_minutes,
                         peak_rr_at_close
    Breakeven:           breakeven_triggered, breakeven_sl_price,
                         breakeven_trigger_time_minutes, mfe_at_breakeven_pips/r,
                         mfe_after_be_pips/r
    R milestones:        time_to_0_5r through time_to_5r_minutes (7 fields)
    UNTP snapshots:      56 columns — 14 checkpoints × 4 fields
                         (mfe_at_Xh_r, mae_at_Xh_r, outcome_at_Xh, alive_at_Xh)
    Entry quality:       first_candle_direction, consecutive_adverse_candles,
                         avg_candle_size_pips_at_entry
    Session:             entry_day_of_week, entry_hour, entry_session
    Streak:              channel_streak_at_save
    Integrity:           price_path_captured
    Path:                mfe_path_json
    UNTP notes:          untp_notes  ← added 2026-03-13

Trade.to_dict()
  Serialises ALL ~140 Trade fields to a plain Python dict.
  This is the ONLY path that converts Trade ORM objects to data
  for the statistics engine. Never access ORM attributes directly
  in statistics — always go through to_dict().
  Returns: dict with string keys matching column names exactly.

Trade.__repr__()
  Returns formatted string for debug/log output.
```

---

### data_loader.py

```
_stored_files_dir()  [private]
  Returns absolute path to "Stored files" directory.
  Uses __file__ if available, else os.getcwd().
  Called once at module level — not a reusable utility.

data_frames  [module-level dict, not a function]
  Populated at import time by iterating SYMBOLS.
  Keys: uppercase symbol strings (e.g. "EURUSD", "NAS100").
  Values: pandas DataFrames with columns: Local time, Open, High, Low, Close.
  NAS100 key is "NAS100" even though file is USTEC.parquet.
  If a symbol fails to load, its key is absent — no error raised at import.
  Consumed exclusively by: utils/mfe_calculator.py

Module-level loading loop  [not a function — runs on import]
  For each sym in SYMBOLS:
    1. Resolves filename via get_file_name(sym)
    2. Reads parquet from Stored files/{filename}.parquet
    3. Parses "Local time" column (format: %d.%m.%Y %H:%M:%S)
    4. Drops rows with NaT timestamps or missing OHLC
    5. Stores result in data_frames[sym.upper()]
    On error: logs logger.error(...) and continues — does not raise.
```

---

### routes/save_routes.py

```
save_trade()
  Route: POST /save_trade
  Orchestrates the complete trade save flow:
    1. _parse_form(request.form) → validated dict
    2. _get_or_create_channel(...) → Channel ORM object
    3. mfe_calculator.calculate_mfe(...) → ~140-key metrics dict
    4. Constructs Trade() with all fields explicitly named
    5. db.session.add(trade) + db.session.commit()
    6. Returns JSON {success, trade_id, channel_name, price_path_captured}
  Error handling:
    ValueError → rollback + JSON 400
    Exception  → rollback + JSON 500
  Note: Trade() uses ~140 explicitly named kwargs — never **mfe dict.

list_channels_json()
  Route: GET /channels/list_json
  Returns JSON array of non-archived channels for the save modal dropdown.
  Each item: {channel_id, name, color}.
  Ordered by name.

_parse_form(form)  [private]
  Validates and normalises the save form POST body.
  Required fields: symbol, trade_type, entry_time, entry_price, stoploss_price.
  Parses entry_time as datetime (format: %Y-%m-%d %H:%M).
  Normalises breakeven_active to bool.
  Normalises trade_type to lowercase.
  Normalises symbol to uppercase.
  Returns: clean dict of all parsed fields.
  Raises ValueError with specific field name on any failure.

_get_or_create_channel(channel_id, new_channel_name,
                        new_channel_description, new_channel_color)  [private]
  If channel_id == "new": creates new Channel, flushes session.
  If channel_id is int string: looks up existing Channel.
  Guards: archived channels rejected, duplicate names rejected,
          invalid channel_id string rejected.
  Returns: Channel ORM object (in session, not yet committed).
  Raises ValueError with descriptive message on any failure.

_f(val)  [private]
  Parses a string or None to float, returns None on empty/invalid.
  Used internally by _parse_form for optional numeric fields.
```

---

### routes/channel_routes.py

```
channels_list()
  Route: GET /channels
  Fetches all channel metadata via get_all_channel_metas().
  Accepts query param ?archived=1 to include archived channels.
  Renders channels.html with metas list and show_archived flag.

create_channel_route()
  Route: POST /channels/create
  Extracts name, description, color from form.
  Delegates to trade_storage.create_channel().
  Returns JSON {success} or {success: false, error}.

rename_channel_route(channel_id)
  Route: POST /channels/<id>/rename
  Extracts new_name from form.
  Delegates to trade_storage.rename_channel().
  Returns JSON {success} or error.

archive_channel_route(channel_id)
  Route: POST /channels/<id>/archive
  Delegates to trade_storage.archive_channel().
  Returns JSON {success} or error.

unarchive_channel_route(channel_id)
  Route: POST /channels/<id>/unarchive
  Delegates to trade_storage.unarchive_channel().
  Returns JSON {success} or error.

delete_channel_route(channel_id)
  Route: POST /channels/<id>/delete
  Parses force flag — accepts "1", "true", "yes".
  Delegates to trade_storage.delete_channel(force=force).
  Returns JSON {success} or error.

channel_detail(channel_id)
  Route: GET /channels/<id>
  Main channel view handler. Reads 5 query params:
    symbol, trade_type, outcome, date_from, date_to
  Calls:
    get_channel_by_id()            → channel or 404
    get_trades_by_channel(...)     → filtered trade list
    get_channel_detail_context()   → (meta, filter_options) tuple
    get_all_channels(archived=False) → for move-trade dropdown
  Renders channel_detail.html with all context.

delete_trade_route(trade_id)
  Route: POST /trades/<id>/delete
  Delegates to trade_storage.delete_trade().
  Returns JSON {success, channel_id}.
  channel_id returned as plain int (captured before commit).

move_trade_route(trade_id)
  Route: POST /trades/<id>/move
  Parses new channel_id from form.
  Delegates to trade_storage.move_trade().
  Returns JSON {success, new_channel_id}.

update_trade_notes(trade_id)
  Route: POST /trades/<id>/notes
  AJAX endpoint for inline notes editing (TP drawer).
  Updates trade.notes, commits.
  Returns JSON {success}.
  Does NOT touch trade.untp_notes.

update_untp_notes(trade_id)
  Route: POST /trades/<id>/untp-notes
  AJAX endpoint for UNTP drawer notes editing.
  Updates trade.untp_notes, commits.
  Returns JSON {success}.
  Does NOT touch trade.notes. Added 2026-03-13.

export_channel_csv(channel_id)
  Route: GET /channels/<id>/export
  Accepts same filter params as channel_detail.
  Delegates to trade_storage.export_trades_csv().
  Returns streaming CSV response with Content-Disposition header.
  Filename sanitised: non-alphanumeric chars replaced with underscore.
```

---

### routes/statistics_routes.py

```
statistics_hub()
  Route: GET /statistics
  Queries all non-archived channels.
  Queries distinct Trade.symbol values across all trades.
  Builds time_limit_options list from TIME_LIMIT_LABELS.
  Renders statistics.html with channels, symbols, time_limit_options.

statistics_overview()
  Route: POST /statistics/overview
  Accepts JSON body:
    {channel_ids, date_from, date_to, symbol, trade_type,
     tp_mode, tp_value, time_limit_hours}
  Validates tp_mode (must be original_tp/fixed_rr/fixed_pips).
  Validates tp_value (required and positive for fixed modes).
  Calls _load_trades(data) → list of Trade ORM objects.
  Calls trade.to_dict() for each → list of plain dicts.
  Calls trade_statistics.compute_overview() → result dict.
  Returns JSON result dict.
  On error: returns JSON {error: ...} with HTTP 400 or 500.

statistics_symbols()
  Route: POST /statistics/symbols
  Accepts JSON {channel_ids: [...]}.
  Returns distinct symbols for the given channels.
  Used to repopulate the symbol dropdown when channel selection changes.
  Returns JSON {symbols: [...]}.

_load_trades(filters)  [private]
  Builds a Trade SQLAlchemy query from the filter dict.
  Supports: channel_ids (IN filter), date_from, date_to,
            symbol (exact match), trade_type (with buy_side/sell_side groups).
  CRITICAL: orders by Trade.entry_time ASC — required for correct equity curve.
  Returns: list of Trade ORM objects.

_parse_float(value)  [private]
  Converts value to float or returns None.
  Used to safely parse tp_value and time_limit_hours from JSON body.
```

---

### utils/mfe_calculator.py

```
calculate_mfe(entry_time, entry_price, stoploss_price, takeprofit_price,
              trade_type, symbol, limit_price, breakeven_active,
              breakeven_type, breakeven_value, input_type, channel_id)
  PUBLIC ENTRY POINT. Called exclusively by save_routes.save_trade().
  Full execution path:
    1. Validates symbol in data_frames
    2. Computes sl_distance_pips, tp_rr_target, tp_pips_target
    3. For pending orders: finds trigger candle
    4. Measures entry quality (first_candle_direction, adverse_candles, avg_size)
    5. Runs main candle loop (steps a–g per candle)
    6. Post-walk cleanup (dip phantom + BE phantom)
    7. Derives outcome_stored, pnl_r_out, retracement
    8. Calls _compute_streak(channel_id)
    9. Classifies session via _classify_session(entry_hour)
   10. Builds and returns complete ~140-key result dict
  On any exception: catches all, logs WARNING, returns _empty_result().
  Returns: dict with keys matching Trade column names exactly.

_compute_streak(channel_id)  [private]
  Queries Trade table: filter by channel_id, ORDER BY entry_time DESC.
  Walk logic:
    hit_tp  → sign = +1 (win)
    hit_sl  → sign = -1 (loss)
    hit_be / open / none → continue (skip — neutral)
  Accumulates streak until sign changes, then breaks.
  Returns: int (positive=win streak, negative=loss streak, 0=first/none).
  RULE: ORDER BY entry_time DESC — never saved_at.
  RULE: hit_be must hit continue before the loss branch.

_empty_result()  [private]
  Returns a fully-keyed dict with all ~140 keys set to None
  and price_path_captured=False.
  Guarantees Trade() constructor never receives missing keyword arguments
  regardless of where calculate_mfe() exits early.
  Must be kept in sync with the final result dict keys.

_classify_session(hour)  [private]
  Maps UTC hour integer to trading session string.
  Returns: "asian" (0–7), "london" (8–12), "overlap" (13–16),
           "new_york" (17–20), "off_hours" (21–23).

MODULE-LEVEL CONSTANTS (not functions — referenced throughout):
  CHECKPOINT_MINUTES  [30,60,120,240,480,720,1440,2880,4320,7200,10080,14400,20160,30240]
  CHECKPOINT_KEYS     ["30min","1h","2h","4h","8h","12h","24h","48h","72h",
                       "120h","168h","240h","336h","504h"]
  UNTP_CAP_MINUTES    30240  (504h = 21 days)
  PATH_INTERVAL_MIN   15
  R_MILESTONES        [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0]
  PENDING_TYPES       {"limit_buy","limit_sell","stop_buy","stop_sell"}
```

**Internal walk logic (not separate functions — all inside calculate_mfe):**

```
Candle loop — step a: elapsed time update
  elapsed_minutes accumulates per candle using candle timestamp delta.

Candle loop — step b: R milestone recording
  For each R in R_MILESTONES: if MFE first crosses threshold,
  record time_to_Xr_minutes. Each milestone fires only once.

Candle loop — step c: dip check
  buy:  if candle.Low < entry → adverse pips = (entry - low) / pip_size
  sell: if candle.High > entry → adverse pips = (high - entry) / pip_size
  Records peak_dip_pips and peak_dip_time.
  Only active before first favourable candle close.

Candle loop — step d: BE trigger check
  If breakeven_active AND peak_mfe_pips >= be_threshold_pips:
    be_triggered = True
    current_sl = entry_price  (effective SL moves to entry)
    record be_trigger_min and mfe_at_be values

Candle loop — step e: SL check
  buy:  candle.Low  <= current_sl → resolution
  sell: candle.High >= current_sl → resolution
  Outcome: "hit_be" if be_triggered, else "hit_sl"

Candle loop — step f: TP check
  buy:  candle.High >= takeprofit_price → hit_tp
  sell: candle.Low  <= takeprofit_price → hit_tp
  Sets trade_fully_closed = True, exit_price = takeprofit_price

Candle loop — step g: UNTP snapshot
  If elapsed_minutes >= CHECKPOINT_MINUTES[next_snap_idx]:
    snaps[i] = {mfe_r, mae_r, outcome (trade state), alive (UNTP state)}
    Advances to next checkpoint index.

UNTP frozen-backfill logic (inside loop, triggers on UNTP stop):
  When untp_stopped fires (SL/entry retrace/504h cap):
    untp_mfe_frozen = peak_mfe_pips (at stop moment)
    untp_mae_frozen = peak_mae_pips (at stop moment)
    Immediately backfills all remaining unrecorded checkpoints
    with frozen values and alive=False.
    Prevents candle movement after UNTP stop from inflating metrics.

mfe_path sampling (inside loop):
  if elapsed_minutes >= last_path_min + PATH_INTERVAL_MIN:
    mfe_path.append([elapsed_min, mfe_r, mae_r, untp_alive])
    last_path_min += PATH_INTERVAL_MIN  ← MUST use +=, not = elapsed_min

Post-walk: dip phantom cleanup
  if dip_occurred AND peak_dip_time >= resolution_candle_time:
    zero all dip fields (peak_dip_pips, peak_dip_time, dip_occurred)

Post-walk: BE phantom cleanup
  if outcome == "hit_tp" AND be_triggered AND be_trigger_min == resolution_min:
    clear all BE fields (be_triggered, current_sl, be_trigger_min, mfe_at_be values)
```

---

### utils/pip_utils.py

```
get_pip_size(symbol)
  SINGLE SOURCE OF TRUTH for pip sizes.
  Input: symbol string (case-insensitive).
  Rules applied in order:
    XAUUSD           → 0.1
    XAGUSD           → 0.01
    NAS100 or US30   → 1.0
    USOIL or UKOIL   → 0.1
    symbol contains "JPY" → 0.01
    all others       → 0.0001
  Returns: float pip size.
  NEVER replicate this logic. Always call this function.
  Any new symbol with non-standard pip size must be added here first.
```

---

### utils/datetime_utils.py

```
validate_datetime_input(form)
  Parses entry_date and entry_time fields from the monitor form POST body.
  Combines into a single datetime object.
  Returns: tuple (datetime | None, error_str | None).
  On success: (datetime_obj, None).
  On failure: (None, descriptive error string).
  Called by: app.py :: monitor_trade_route() only.
```

---

### utils/symbols.py

```
MAJOR_PAIRS  [module-level list constant]
  33 forex pairs.

EXTRA_INSTRUMENTS  [module-level list constant]
  6 instruments: XAUUSD, XAGUSD, NAS100, US30, USOIL, UKOIL.

SYMBOLS  [module-level list constant]
  MAJOR_PAIRS + EXTRA_INSTRUMENTS = 39 total.
  Used by: app.py (monitor dropdown), data_loader.py (parquet loading).
```

---

### utils/trade_calculations.py

```
get_file_name(symbol)
  Applies FILE_NAME_MAPPING to resolve parquet filename from symbol.
  FILE_NAME_MAPPING = {"NAS100": "USTEC"}
  If symbol not in mapping: returns symbol.upper().
  Returns: string filename (no extension).
  Used by: data_loader.py and get_closing_price() in this file.

get_closing_price(year, month, day, hour, minute, symbol)
  Loads parquet file for symbol directly (no caching — reads from disk).
  Finds the first candle at or after the given timestamp.
  Returns: float close price.
  Raises: FileNotFoundError if parquet missing.
  Raises: ValueError if no data found.
  WARNING: reads from disk every call. Only used at monitor time.
  NOT used at save time — mfe_calculator uses data_frames cache instead.

calculate_pips(entry_price, target_price, symbol)
  Computes pip distance between two prices.
  Contains its own pip size logic (duplicates pip_utils.py).
  PREFER pip_utils.get_pip_size() for authoritative pip sizes.
  Returns: float pip count.

_stored_files_dir()  [private]
  Returns absolute path to "Stored files" directory.
  Same pattern as data_loader._stored_files_dir().
```

---

### utils/trade_monitor.py  ⛔ READ-ONLY

```
monitor_trade(entry_time, stoploss_price, takeprofit_price, trade_type,
              breakeven, symbol, breakeven_rr, breakeven_type,
              breakeven_pips, limit_price, expiry_days, expiry_hours,
              expiry_minutes, close_trade_time)
  Original trade monitor engine. READ-ONLY — NEVER MODIFY.
  Runs a trade simulation and returns a list of plain-text result lines.
  These lines are displayed to the user in results.html.
  Called by: app.py :: monitor_trade_route() only.
  Returns: list of strings.
```

---

### utils/trade_statistics.py

```
compute_overview(trades, tp_mode, tp_value, time_limit_hours)
  MODULE 1 ENTRY POINT. Pure function — no Flask, no DB.
  Input: list of trade dicts from Trade.to_dict(), ordered by entry_time ASC.
  Flow:
    1. Splits trades: excluded (price_path_captured=False) vs good
    2. Calls resolve_win_loss() for each good trade
    3. Computes: wins, losses, inconclusive counts
    4. Computes: win_rate, net_rr, expectancy
    5. Builds equity_curve via _effective_pnl() per evaluated trade
    6. Builds drawdown_curve from equity curve
    7. Computes: avg_mfe_r, avg_mae_r, avg_win_r, avg_loss_r
    8. Computes: max_win_streak, max_loss_streak
    9. Counts outcome_breakdown (raw pie chart data)
  Returns: complete result dict with all metrics + curves + metadata.

resolve_win_loss(trade, tp_mode, tp_value, time_limit_hours)
  Classifies a single trade as "win", "loss", or "inconclusive".
  PRECONDITION: trade["price_path_captured"] must be True (caller filters).
  Three tp_mode branches:
    "original_tp":
      hit_tp → win
      hit_sl or hit_be → loss  ← hit_be IS a loss in this mode
      open / none → inconclusive
    "fixed_rr" or "fixed_pips" (UNTP-based):
      With time_limit: use mfe_at_Xh_r column
        alive_at_Xh=False → inconclusive (UNTP stopped before checkpoint)
        alive_at_Xh=True AND mfe >= target → win
        alive_at_Xh=True AND mfe < target → loss
      Without time_limit: use mfe_r (trade walk peak)
        mfe >= target → win
        mfe < target AND outcome in (hit_sl, hit_be) → loss
        otherwise → inconclusive
  CRITICAL RULE: denominator is ALWAYS alive_at_Xh=True. Never COUNT(*).

_effective_pnl(trade, tp_mode, tp_value, result)  [private]
  Returns per-trade P&L float for equity curve construction.
  result must be "win" or "loss" (inconclusive trades excluded from curve).
  original_tp:  uses stored trade["pnl_r"]
  fixed_rr:     win=+tp_value, loss=-1.0
  fixed_pips:   win=tp_value/sl_distance_pips (per-trade R), loss=-1.0

_get_snapshot_cols(time_limit_hours)  [private]
  Maps float time limit to (mfe_column_name, alive_column_name) tuple.
  Performs exact lookup in _TIME_LIMIT_MAP.
  If no exact match: snaps to nearest checkpoint (logs warning).
  Returns (None, None) for time_limit_hours=None (use mfe_r instead).

_TIME_LIMIT_MAP  [module-level dict constant]
  Maps float hours → (mfe_col, alive_col) pairs.
  Keys: None, 0.5, 1.0, 2.0, 4.0, 8.0, 12.0, 24.0, 48.0, 72.0,
        120.0, 168.0, 240.0, 336.0, 504.0.

TIME_LIMIT_LABELS  [module-level dict constant]
  Maps float hours → human-readable label strings.
  Exported to statistics_routes.py for the time limit dropdown.

  compute_fixed_untp_overview(trades, tp_value, time_limit_hours, unit='R') → dict
  Fixed UNTP win-rate analysis. Win = mfe_at_Xh_r >= target (UNTP peak, frozen at
  stop if walk ended early). alive_at_Xh irrelevant. Returns result_type='overview'
  so renderOverview() handles it unchanged. Inconclusive = mfe_at_Xh_r is None.

_classify_for_hitrate(trade, tp_mode, tp_value, unit, mfe_col, alive_col) → tuple[str, float]
  Per-trade classifier for hit rate rows. Returns (bucket, pnl).
  original_tp/fixed_tp → delegates to resolve_win_loss + _effective_pnl.
  fixed_untp → mfe_at_Xh_r vs target; alive irrelevant (BUG-16).
  untp_overview → open/sl/be buckets (DECISION-12).

_build_hitrate_rows(groups, tp_mode, tp_value, unit, mfe_col, alive_col, sort_by_label_order) → list[dict]
  Builds one dimension's row list from {label: [trades]} dict.
  Calls _classify_for_hitrate per trade. Excludes price_path_captured=False.
  Sorts by count desc unless sort_by_label_order provided (used for day_of_week).

compute_hit_rate(trades, tp_mode, tp_value, time_limit_hours, unit) → dict
  Module 2 entry point. Returns result_type='hitrate' with dimensions dict
  containing symbol/trade_type/session/day_of_week row lists.
  All 4 modes supported. Weekend/null trades excluded from day_of_week dimension.

```

---

### utils/trade_storage.py

```
get_all_channels(include_archived)
  Returns all Channel objects ordered by name.
  If include_archived=False: filters is_archived=False.

get_channel_by_id(channel_id)
  Returns single Channel or None.

create_channel(name, description, color)
  Validates name non-empty and unique.
  Creates Channel, commits. Returns Channel.
  Raises ValueError on empty name or duplicate.

rename_channel(channel_id, new_name)
  Validates new_name non-empty and unique (excluding self).
  Updates channel.name, commits. Returns Channel.
  Raises ValueError on validation failure or not found.

archive_channel(channel_id)
  Sets is_archived=True, commits.
  Guards against no-op: raises ValueError if already archived.

unarchive_channel(channel_id)
  Sets is_archived=False, commits.
  Guards against no-op: raises ValueError if not archived.

delete_channel(channel_id, force)
  If trade_count > 0 and not force: raises ValueError.
  Uses synchronize_session="fetch" for bulk Trade delete.
  Calls db.session.delete(channel), commits.
  IMPORTANT: synchronize_session="fetch" is required to avoid
  stale ORM objects causing FK constraint violations.

get_channel_meta(channel_id, _trades)
  Builds channel metadata dict from Channel + trade list.
  Pass _trades to avoid extra DB round-trip.
  Returns dict with: channel_id, name, description, color,
  is_archived, created_at, trade_count, date_from, date_to,
  symbols, has_bad_trades, bad_trade_count.

_build_channel_meta(channel, trades)  [private]
  Internal helper. Derives meta dict from pre-loaded trade list.
  Handles zero-trade edge case (returns empty range/symbols).

get_all_channel_metas(include_archived)
  OPTIMISED: 2 total queries (not N+1).
  Query 1: all channels.
  Query 2: all trades for those channels (single IN query).
  Groups trades by channel_id in Python.
  Returns: list of meta dicts, one per channel.

get_trades_by_channel(channel_id, symbol, trade_type,
                       outcome, date_from, date_to)
  Filtered Trade query for channel detail page.
  Supports: symbol (exact), trade_type (with buy_side/sell_side groups),
            outcome (exact), date_from (>=), date_to (<+1day).
  Orders by entry_time DESC.
  Returns: list of Trade ORM objects.

get_trade_by_id(trade_id)
  Returns single Trade or None.

delete_trade(trade_id)
  Captures channel_id as plain int BEFORE commit.
  Calls db.session.delete(trade), commits.
  Returns: int channel_id.
  IMPORTANT: capture before commit to avoid DetachedInstanceError.

move_trade(trade_id, new_channel_id)
  Validates: trade exists, destination channel exists, not archived,
             not same channel.
  Updates trade.channel_id, commits.
  Returns: int new_channel_id (captured before commit).

get_incomplete_trades(channel_id)
  Returns trades where price_path_captured=False.
  Used for identifying trades that need re-saving.

get_channel_filter_options(channel_id, _trades)
  Returns {symbols, outcomes, trade_types} for channel detail dropdowns.
  Pass _trades to share query with get_channel_meta().

get_channel_detail_context(channel_id)
  Loads ALL (unfiltered) trades for channel ONCE.
  Derives both meta and filter_options from that single list.
  Returns: tuple (meta_dict, filter_options_dict).
  Saves one Trade query compared to calling each function separately.

export_trades_csv(channel_id, symbol, trade_type,
                  outcome, date_from, date_to)
  Calls get_trades_by_channel() with filters.
  Writes CSV using _CSV_COLUMNS field list.
  Returns: CSV string (in-memory StringIO).
  KNOWN GAP (P2-GAP-1): _CSV_COLUMNS missing 56 UNTP columns + mfe_path_json.

_CSV_COLUMNS  [module-level list constant]
  Defines which Trade fields appear in CSV export.
  Currently 33 fields — excludes all UNTP snapshot columns.
  Fix in Phase 5: add all 56 UNTP columns + mfe_path_json.
```

---

### utils/trade_validation.py

```
validate_trade_inputs(entry_price, stoploss_price, takeprofit_price,
                       trade_type, current_price, symbol, limit_price)
  Validates all price relationships for monitor form inputs.
  Checks: prices positive and non-zero, entry != SL != TP.
  Checks direction rules by trade type:
    buy/limit_buy/stop_buy:  SL < entry, TP > entry
    sell/limit_sell/stop_sell: SL > entry, TP < entry
  Checks limit/stop price direction vs current_price.
  Returns None on success. Raises ValueError on failure.
  Called by: process_trade_inputs().

validate_trade_type(form_data)
  Extracts and validates trade_type from form dict.
  Valid values: buy, sell, limit_buy, limit_sell, stop_buy, stop_sell.
  Returns: normalised lowercase trade_type string.
  Raises ValueError on invalid value.

process_trade_inputs(request, trade_type, entry_time,
                      get_closing_price_func, symbol)
  Master input processor for the monitor form.
  Flow:
    1. Validates input_type (prices/pips/rr)
    2. Gets current_price via get_closing_price_func()
    3. For pending orders: parses limit_price
    4. Converts SL/TP to absolute prices based on input_type:
       prices: reads stoploss_price/takeprofit_price directly
       pips:   computes from entry ± pips × pip_size × direction
       rr:     computes TP from entry ± risk × rr_ratio × direction
    5. Calls validate_trade_inputs() for final validation
  Returns: (limit_price, stoploss_price, takeprofit_price, input_type).
  Raises ValueError with descriptive message on any failure.

validate_breakeven_input(request)
  Parses breakeven form fields.
  If not enabled: returns (False, None, None).
  If enabled: validates type (rr/pips) and value (positive float).
  Returns: (bool, type_str, value_float).
  Raises ValueError on invalid configuration.

validate_expiry_input(request, trade_type)
  Only active for pending order types (limit/stop).
  Validates expiry_enabled flag, then days/hours/minutes.
  Guards: all three fields required, all non-negative,
          total duration must be non-zero if enabled.
  Returns: (expiry_enabled, days, hours, minutes).
  For market orders: returns (False, 0, 0, 0) without validation.
```

---

### templates/channel_detail.html

```
renderDrawerContent(trade)
  Renders the full TP trade detail drawer into #drawer-body.
  Strict const declaration order (TDZ — no forward references ever):
    1. DAYS / streakVal / _outcome
    2. _streakIsNeutral / streakDisplay
    3. ref / _refMfe / _refMae / _refStopped
    4. _dip / _advCandles
    5. shapeName (+ shape condition variables)
    6. metrics block
    7. refLabel
    8. innerHTML assignment

openDrawer(trade) / closeDrawer()
  Manages TP drawer open/close state, overlay, keyboard nav.

── UNTP Dual-Section Functions (added 2026-03-13) ──────────────

setPageView(view)
  Switches between 'tp' and 'untp' page sections.
  Toggles visibility of #tp-section and #untp-section.
  Calls renderUntpTable() on first switch to UNTP.

resolveUntpAtWindow(t, targetMins) → { mfe, mae, alive, resolvedMins, fromPath }
  Returns UNTP state for a trade at targetMins.
  Priority: 1. exact checkpoint match → stored fields.
            2. mfe_path_json walk → last entry where elapsed_min <= targetMins.
            3. nearest checkpoint fallback.
  BUG-3 aware: path entries are [elapsed_min, mfe_r, mae_r, untp_alive].

classifyUntpTrade(t, targetMins) → { bucket, pnl, mfe, mae, alive } | null
  Running = alive=true. Loss = !alive + !be_triggered → -1.0.
  BE = !alive + be_triggered → 0.0.
  Returns null for trades without price path data.

untpPeakMfe(t) → float
  Highest mfe_at_Xh_r across all 14 checkpoints where alive_at_Xh=true.
  Falls back to t.mfe_r if no alive checkpoints.

untpLastAliveIdx(t) → int (0–13) or -1
  Index of last checkpoint where alive_at_Xh=true. -1 if none alive.

onUntpPageSlider()
  Slider oninput handler. Updates _untpPageMins, syncs numeric box + resolved label.
  Calls renderUntpTable() and renderUntpDrawerContent() if drawer open.

onUntpPageBox()
  Numeric input oninput handler. Updates _untpPageMins, snaps slider to nearest CP.
  Calls renderUntpTable() and renderUntpDrawerContent() if drawer open.

renderUntpTable()
  Builds UNTP table rows and UNTP PnL bar from current _untpPageMins.
  Rows call openUntpDrawer(). Excludes price_path_captured=false trades.

openUntpDrawer(tradeId)
  Opens #untpDrawer for given trade. Sets _untpOpenTradeId.
  Calls renderUntpDrawerContent.

closeUntpDrawer()
  Hides #untpDrawer and #untpDrawerOverlay. Clears _untpOpenTradeId.

renderUntpDrawerContent(t)
  Renders all 9 UNTP drawer sections into #untp-drawer-body using _untpPageMins.
  Sections: hero, peak, @window, geometry, milestones, BE, pending, untp_notes, data.
  Uses classifyUntpTrade(), resolveUntpAtWindow(), untpPeakMfe(), untpLastAliveIdx().

saveUntpNotes(tradeId)
  POSTs textarea value to /trades/<id>/untp-notes.
  Updates TRADES[id].untp_notes in memory on success.
```

---

## SECTION 2 — QUICK FUNCTION LOOKUP

```
TRADE CALCULATION / WALK ENGINE
────────────────────────────────────────────────────────────────
Run the trade walk + UNTP walk
  → calculate_mfe()
  → utils/mfe_calculator.py

Compute channel streak
  → _compute_streak(channel_id)
  → utils/mfe_calculator.py

Classify trading session (asian/london/etc)
  → _classify_session(hour)
  → utils/mfe_calculator.py

Get empty result on walk failure
  → _empty_result()
  → utils/mfe_calculator.py

STATISTICS
────────────────────────────────────────────────────────────────
Module 1 performance overview
  → compute_overview(trades, tp_mode, tp_value, time_limit_hours)
  → utils/trade_statistics.py

Classify single trade as win/loss/inconclusive
  → resolve_win_loss(trade, tp_mode, tp_value, time_limit_hours)
  → utils/trade_statistics.py

Per-trade P&L for equity curve
  → _effective_pnl(trade, tp_mode, tp_value, result)
  → utils/trade_statistics.py

Map time limit to UNTP snapshot columns
  → _get_snapshot_cols(time_limit_hours)
  → utils/trade_statistics.py

PIP SIZES
────────────────────────────────────────────────────────────────
Get pip size for any symbol
  → get_pip_size(symbol)
  → utils/pip_utils.py

PRICE / DATA LOOKUPS
────────────────────────────────────────────────────────────────
Get closing price from parquet (monitor time)
  → get_closing_price(year, month, day, hour, minute, symbol)
  → utils/trade_calculations.py

Resolve parquet filename from symbol
  → get_file_name(symbol)
  → utils/trade_calculations.py

Calculate pip distance between two prices
  → calculate_pips(entry_price, target_price, symbol)
  → utils/trade_calculations.py

VALIDATION
────────────────────────────────────────────────────────────────
Monitor form: full input processing (SL/TP/direction)
  → process_trade_inputs(request, trade_type, entry_time, func, symbol)
  → utils/trade_validation.py

Monitor form: validate trade type string
  → validate_trade_type(form_data)
  → utils/trade_validation.py

Monitor form: validate all price relationships
  → validate_trade_inputs(entry, sl, tp, type, current, symbol, limit)
  → utils/trade_validation.py

Monitor form: parse and validate breakeven
  → validate_breakeven_input(request)
  → utils/trade_validation.py

Monitor form: parse and validate expiry (pending orders)
  → validate_expiry_input(request, trade_type)
  → utils/trade_validation.py

Save form: parse and validate POST body
  → _parse_form(form)
  → routes/save_routes.py

DATETIME
────────────────────────────────────────────────────────────────
Parse entry datetime from monitor form
  → validate_datetime_input(form)
  → utils/datetime_utils.py

DATABASE — CHANNELS
────────────────────────────────────────────────────────────────
Get all channels (with optional archived)
  → get_all_channels(include_archived)
  → utils/trade_storage.py

Get channel by ID
  → get_channel_by_id(channel_id)
  → utils/trade_storage.py

Create channel
  → create_channel(name, description, color)
  → utils/trade_storage.py

Rename channel
  → rename_channel(channel_id, new_name)
  → utils/trade_storage.py

Archive / unarchive channel
  → archive_channel(channel_id) / unarchive_channel(channel_id)
  → utils/trade_storage.py

Delete channel (with optional force)
  → delete_channel(channel_id, force)
  → utils/trade_storage.py

Get channel metadata card dict
  → get_channel_meta(channel_id, _trades)
  → utils/trade_storage.py

Get all channel metadata (N+1 safe)
  → get_all_channel_metas(include_archived)
  → utils/trade_storage.py

DATABASE — TRADES
────────────────────────────────────────────────────────────────
Get trades for channel (with filters)
  → get_trades_by_channel(channel_id, symbol, trade_type, outcome, date_from, date_to)
  → utils/trade_storage.py

Get single trade by ID
  → get_trade_by_id(trade_id)
  → utils/trade_storage.py

Delete trade
  → delete_trade(trade_id)
  → utils/trade_storage.py

Move trade to different channel
  → move_trade(trade_id, new_channel_id)
  → utils/trade_storage.py

Export trades to CSV
  → export_trades_csv(channel_id, ...)
  → utils/trade_storage.py

Save TP drawer notes
  → update_trade_notes(trade_id)  [POST /trades/<id>/notes]
  → routes/channel_routes.py

Save UNTP drawer notes
  → update_untp_notes(trade_id)  [POST /trades/<id>/untp-notes]
  → routes/channel_routes.py

UNTP DUAL-SECTION (channel_detail.html JS)
────────────────────────────────────────────────────────────────
Switch page between TP and UNTP views
  → setPageView(view)
  → templates/channel_detail.html

Resolve UNTP state at arbitrary window
  → resolveUntpAtWindow(t, targetMins)
  → templates/channel_detail.html

Classify UNTP trade as Running/Loss/BE
  → classifyUntpTrade(t, targetMins)
  → templates/channel_detail.html

Get peak MFE across all alive checkpoints
  → untpPeakMfe(t)
  → templates/channel_detail.html

Get index of last alive checkpoint
  → untpLastAliveIdx(t)
  → templates/channel_detail.html

Render UNTP table + PnL bar
  → renderUntpTable()
  → templates/channel_detail.html

Open / close UNTP drawer
  → openUntpDrawer(tradeId) / closeUntpDrawer()
  → templates/channel_detail.html

Render UNTP drawer content
  → renderUntpDrawerContent(t)
  → templates/channel_detail.html

Save UNTP notes via AJAX
  → saveUntpNotes(tradeId)
  → templates/channel_detail.html
```

---

## SECTION 3 — ROUTE MAP (all routes in the system)

```
GET  /                          index()                     app.py
POST /monitor_trade             monitor_trade_route()       app.py

POST /save_trade                save_trade()                save_routes.py
GET  /channels/list_json        list_channels_json()        save_routes.py

GET  /channels                  channels_list()             channel_routes.py
POST /channels/create           create_channel_route()      channel_routes.py
POST /channels/<id>/rename      rename_channel_route()      channel_routes.py
POST /channels/<id>/archive     archive_channel_route()     channel_routes.py
POST /channels/<id>/unarchive   unarchive_channel_route()   channel_routes.py
POST /channels/<id>/delete      delete_channel_route()      channel_routes.py
GET  /channels/<id>             channel_detail()            channel_routes.py
GET  /channels/<id>/export      export_channel_csv()        channel_routes.py

POST /trades/<id>/delete        delete_trade_route()        channel_routes.py
POST /trades/<id>/move          move_trade_route()          channel_routes.py
POST /trades/<id>/notes         update_trade_notes()        channel_routes.py
POST /trades/<id>/untp-notes    update_untp_notes()         channel_routes.py  ← added 2026-03-13

GET  /statistics                statistics_hub()            statistics_routes.py
POST /statistics/overview       statistics_overview()       statistics_routes.py
POST /statistics/symbols        statistics_symbols()        statistics_routes.py
```

---

## SECTION 4 — DEPENDENCY CHAINS

### Save Trade Chain
```
POST /save_trade (browser)
        │
        ▼
save_trade()  [routes/save_routes.py]
        │
        ├──► _parse_form(request.form)
        ├──► _get_or_create_channel(...)
        │         └──► trade_storage.create_channel() (if new)
        ├──► mfe_calculator.calculate_mfe(...)
        │         ├──► data_loader.data_frames  (read-only)
        │         ├──► pip_utils.get_pip_size()
        │         ├──► _compute_streak(channel_id)
        │         │         └──► db.Trade  (query only)
        │         └──► _classify_session(hour)
        ├──► Trade(**all_fields)
        └──► db.session.commit()
        │
        ▼
JSON {success, trade_id, price_path_captured}
```

### Statistics Chain
```
POST /statistics/overview (browser fetch)
        │
        ▼
statistics_overview()  [routes/statistics_routes.py]
        │
        ├──► _load_trades(filters)
        │         └──► Trade SQLAlchemy query (ORDER BY entry_time ASC)
        ├──► trade.to_dict() for each Trade
        └──► trade_statistics.compute_overview(trades, ...)
                  ├──► resolve_win_loss(trade, ...)
                  │         └──► _get_snapshot_cols(time_limit_hours)
                  └──► _effective_pnl(trade, ...)
        │
        ▼
JSON result → statistics.html charts
```

### Channel Detail Chain
```
GET /channels/<id> (browser)
        │
        ▼
channel_detail(channel_id)  [routes/channel_routes.py]
        │
        ├──► get_channel_by_id(id)  [utils/trade_storage.py]
        ├──► get_trades_by_channel(id, filters...)  [utils/trade_storage.py]
        ├──► get_channel_detail_context(id)  [utils/trade_storage.py]
        │         ├──► get_channel_meta(id, _trades)
        │         │         └──► _build_channel_meta(channel, trades)
        │         └──► get_channel_filter_options(id, _trades)
        └──► get_all_channels(archived=False)  [utils/trade_storage.py]
        │
        ▼
render_template('channel_detail.html', trades=..., meta=..., ...)
        │
        ▼ (client-side)
renderDrawerContent(trade)  [TP drawer — channel_detail.html JS]
renderUntpDrawerContent(t)  [UNTP drawer — channel_detail.html JS]
        └── no HTTP call — trade data already in page context
```

---

## SECTION 5 — FUNCTION RESPONSIBILITY RULES

```
app.py
  Owns: GET / and POST /monitor_trade only.
  May call: validation utils, trade_monitor, template rendering.
  Must NOT: contain business logic, DB queries, walk logic, statistics.

routes/*.py
  Own: HTTP request parsing, response formatting.
  May call: trade_storage, calculate_mfe, compute_overview, render_template.
  Must NOT: contain walk logic, statistics math, direct ORM queries beyond
            simple filter building.

utils/mfe_calculator.py
  Owns: all trade walk logic, UNTP walk logic, streak computation,
        session classification, mfe_path sampling, post-walk cleanup.
  May import: data_loader.data_frames, pip_utils, db.Trade (streak query only).
  Must NOT: write to DB, import Flask, duplicate pip size rules.

utils/trade_statistics.py
  Owns: all statistics computation — win rate, equity curve, drawdown,
        win/loss classification, UNTP denominator logic.
  May import: nothing from the rest of the project.
  Must NOT: import Flask, import db, import data_loader, write to DB.
  Must be: importable in complete isolation. Pure function.

utils/trade_storage.py
  Owns: all DB reads and writes for Channel and Trade.
  May import: db.py only.
  Must NOT: import Flask, contain statistics logic, contain walk logic.

utils/pip_utils.py
  Owns: pip size rules. Single function. No imports.
  Must NOT: be duplicated anywhere. All pip size logic centralised here.

utils/trade_validation.py
  Owns: monitor-time input validation only.
  Used by: app.py only.
  Must NOT: be called at save time (save-time validation is in _parse_form).

utils/trade_calculations.py
  Owns: price lookups from parquet at monitor time, filename mapping.
  Must NOT: be used at save time (use data_frames cache instead).

utils/trade_monitor.py  ⛔ READ-ONLY
  Owns: original monitor simulation engine.
  Must NEVER be modified.

db.py
  Owns: ORM model definitions and init_db.
  Must NOT: contain business logic.
  to_dict() is the ONLY approved serialisation path for Trade data.

templates/*.html
  Own: UI rendering and client-side display logic.
  May: format and display data already computed server-side.
  Must NOT: derive new analytical values from raw trade fields.
  Must NOT: make implicit assumptions about field presence
            (always guard for null/undefined).
```

---

## SECTION 6 — AI NAVIGATION TIPS

### By task

```
Modifying trade walk outcome logic
  → utils/mfe_calculator.py :: calculate_mfe() candle loop
  → Check step order (a→g), post-walk cleanup, pnl_r assignment (Section 9)

Modifying UNTP snapshot recording
  → utils/mfe_calculator.py :: candle loop step g + snaps[] array
  → Check UNTP frozen-backfill block (runs when untp_stopped fires)

Modifying streak calculation
  → utils/mfe_calculator.py :: _compute_streak()
  → RULE: ORDER BY entry_time DESC, hit_be = continue (skip)

Adding a new UNTP checkpoint or changing checkpoint intervals
  → utils/mfe_calculator.py :: CHECKPOINT_MINUTES + CHECKPOINT_KEYS constants
  → utils/trade_statistics.py :: _TIME_LIMIT_MAP + TIME_LIMIT_LABELS
  → db.py :: add 4 new columns per checkpoint
  → routes/save_routes.py :: add columns to Trade() constructor
  → db.py :: Trade.to_dict() — add new columns
  → user must delete trades.db and migrate

Modifying win/loss classification
  → utils/trade_statistics.py :: resolve_win_loss()
  → RULE: original_tp: hit_be=loss | UNTP modes: alive_at_Xh=True denominator

Adding a new statistics metric
  → utils/trade_statistics.py :: compute_overview() return dict
  → routes/statistics_routes.py :: statistics_overview() (no code change needed)
  → templates/statistics.html :: add rendering for new metric key

Modifying pip size for a symbol
  → utils/pip_utils.py :: get_pip_size()
  → utils/mfe_calculator.py :: local fallback (keep in sync)

Adding a new supported symbol
  → utils/symbols.py :: SYMBOLS list
  → Stored files/{SYMBOL}.parquet :: add file
  → utils/pip_utils.py :: add rule if non-standard pip
  → utils/trade_calculations.py :: FILE_NAME_MAPPING if filename differs

Changing how trades are filtered in channel detail
  → utils/trade_storage.py :: get_trades_by_channel()
  → routes/channel_routes.py :: channel_detail() (reads query params)
  → templates/channel_detail.html :: filter bar UI

Changing how statistics filters work
  → routes/statistics_routes.py :: _load_trades() + statistics_overview()
  → templates/statistics.html :: filter panel JS fetch payload

Adding a new Trade field (schema change)
  → db.py :: Trade model column
  → utils/mfe_calculator.py :: _empty_result() + result dict
  → db.py :: Trade.to_dict()
  → routes/save_routes.py :: Trade() constructor
  → User: delete trades.db + run migration
  → If in CSV: utils/trade_storage.py :: _CSV_COLUMNS

Modifying the UNTP dual-section view
  → templates/channel_detail.html :: setPageView, renderUntpTable, renderUntpDrawerContent
  → Check resolveUntpAtWindow priority order (exact CP → path walk → nearest CP)
  → Check classifyUntpTrade bucket logic (alive=Running regardless of MFE sign)
  → routes/channel_routes.py :: update_untp_notes() for notes endpoint

Debugging a JS crash in the TP trade drawer
  → templates/channel_detail.html :: renderDrawerContent()
  → Check browser console for TDZ ReferenceError
  → Find the const declaration and all its uses
  → Ensure declaration is BEFORE first use in strict order

Debugging a JS crash in the UNTP drawer
  → templates/channel_detail.html :: renderUntpDrawerContent()
  → UNTP drawer is #untpDrawer — completely separate from #tradeDrawer
  → Check resolveUntpAtWindow returns valid { mfe, mae, alive } object

Debugging empty drawer after DB migration
  → All UNTP fields NULL → price_path_captured False OR DB not migrated
  → Check PENDING-1 in MCP.md

Debugging incorrect statistics results
  → utils/trade_statistics.py :: resolve_win_loss() first
  → Check alive_at_Xh denominator rule
  → Check hit_be treatment for the active tp_mode
  → Check _load_trades() uses entry_time ASC

Debugging a channel delete failure
  → utils/trade_storage.py :: delete_channel()
  → Verify synchronize_session="fetch"
  → routes/channel_routes.py :: delete_channel_route()
  → Verify force flag parsing accepts "true" and "1" and "yes"
```

### By file when you don't know the function

```
Something wrong with trade metrics
  → utils/mfe_calculator.py  (start here always)

Something wrong with statistics numbers
  → utils/trade_statistics.py :: resolve_win_loss() first

Something wrong with the save flow
  → routes/save_routes.py :: save_trade() → _parse_form()

Something wrong with the TP channel drawer
  → utils/trade_storage.py :: get_trades_by_channel() (data)
  → templates/channel_detail.html :: renderDrawerContent() (display)

Something wrong with the UNTP section or UNTP drawer
  → templates/channel_detail.html :: resolveUntpAtWindow(), classifyUntpTrade()
  → routes/channel_routes.py :: update_untp_notes() (if notes not saving)

Something wrong with the monitor form
  → utils/trade_validation.py :: process_trade_inputs()
  → app.py :: monitor_trade_route()

Something wrong with pip calculations
  → utils/pip_utils.py :: get_pip_size()

Something wrong with parquet data loading
  → data_loader.py (check startup logs first)

Something wrong with DB not updating
  → db.py — was migration run? (create_all ≠ migration)
  → db.py :: Trade.to_dict() — is new field serialised?
  → routes/save_routes.py — is new field in Trade() constructor?
```