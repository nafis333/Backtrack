# AI_DEBUG_GUIDE.md
# Backtrack — AI Debugging Guide
# Generated: 2026-03-11
# Purpose: Direct AI agents to the correct file immediately when something breaks.
# Read this before opening any source file during a debugging session.

---

## SECTION 1 — HOW THE SYSTEM WORKS (QUICK FLOW)

Understanding the full request lifecycle prevents looking in the wrong layer.

```
MONITOR FLOW (no DB writes)
─────────────────────────────────────────────────────────────────
1. User fills index.html form (symbol, trade type, entry time, SL/TP, BE, expiry)
2. POST /monitor_trade → app.py :: monitor_trade_route()
3. app.py validates inputs via trade_validation.py
4. app.py calls trade_calculations.get_closing_price() to resolve market entry price
5. app.py calls trade_monitor.monitor_trade() [READ-ONLY — never modify]
6. trade_monitor walks parquet candles and produces plain-text result lines
7. app.py extracts actual_entry_price from result lines (3-level fallback)
8. app.py builds save_context dict and renders results.html

SAVE FLOW (DB write)
─────────────────────────────────────────────────────────────────
9.  User reviews results.html, opens Save modal, selects channel
10. POST /save_trade → routes/save_routes.py :: save_trade()
11. save_routes._parse_form() validates and normalises form fields
12. save_routes._get_or_create_channel() resolves or creates the target Channel
13. mfe_calculator.calculate_mfe() runs:
      a. Loads data_frames[symbol] from pre-cached parquet data
      b. For pending orders: finds trigger candle
      c. From entry candle: iterates M1 candles one by one
         Each candle: elapsed → R milestones → dip → BE trigger → SL → TP → UNTP snapshot
      d. After loop exits: post-walk cleanup (dip phantom, BE phantom)
      e. Derives outcome / pnl_r / retracement
      f. Calls _compute_streak() for channel_streak_at_save
      g. Returns ~140-key dict
14. save_routes constructs Trade() with all fields explicitly named
15. db.session.commit() — single transaction
16. Returns JSON {success, trade_id, price_path_captured}
17. results.html JS shows success toast (or warning if price_path_captured=False)

CHANNEL VIEW FLOW (read)
─────────────────────────────────────────────────────────────────
18. GET /channels/<id> → channel_routes.channel_detail()
19. get_trades_by_channel() fetches filtered trades
20. get_channel_detail_context() fetches metadata + filter options (single shared query)
21. renders channel_detail.html with trades, meta, filter_options, all_channels
22. JS in channel_detail.html populates table; row click calls renderDrawerContent(trade)

STATISTICS FLOW (read + compute)
─────────────────────────────────────────────────────────────────
23. GET /statistics → statistics_routes.statistics_hub()
24. User applies filters, clicks compute
25. POST /statistics/overview → statistics_routes.statistics_overview()
26. _load_trades() builds filtered Trade query, ordered by entry_time ASC
27. trade.to_dict() called for each trade
28. trade_statistics.compute_overview() classifies and aggregates
29. Returns JSON result dict → statistics.html renders charts and cards
```

---

## SECTION 2 — MOST COMMON BUG LOCATIONS

```
utils/mfe_calculator.py      ★★★★★  Highest bug surface
  Walk logic, step ordering, post-walk cleanup, UNTP frozen-backfill,
  mfe_path sampling, streak ordering, BE phantom, dip phantom.
  Most production bugs have originated here.

utils/trade_statistics.py    ★★★★
  UNTP denominator (alive_at_Xh vs COUNT(*)), win/loss classification
  per tp_mode, equity curve ordering, hit_be context confusion.

templates/channel_detail.html ★★★★
  JS TDZ crashes (const forward references in renderDrawerContent),
  MFE:MAE ratio denominator, UNTP window selector feeding wrong values,
  RR/Pips toggle state inconsistency.

routes/save_routes.py        ★★★
  Form field parsing, channel creation/resolution, Trade() constructor
  missing a new field after schema change.

utils/trade_storage.py       ★★
  N+1 query regressions, synchronize_session missing on bulk delete,
  DetachedInstanceError from post-commit ORM attribute access.

db.py                        ★★
  Schema change not propagated (create_all doesn't add columns),
  missing field in to_dict() after adding a column.

data_loader.py               ★
  Symbol not loading (file missing, path wrong, parse error),
  data_frames key casing mismatch.

utils/trade_validation.py    ★
  Monitor-time validation rejecting valid inputs, RR mode calculation
  producing wrong SL/TP prices.
```

---

## SECTION 3 — DEBUGGING BY SYMPTOM

### SYMPTOM: Trade saves successfully but all metrics are NULL / empty

**This means price_path_captured=False. The walk engine returned _empty_result().**

Check in this order:

1. **Is the symbol in data_frames?**
   → `data_loader.py`
   The parquet file may be missing, named incorrectly, or have a parse error at startup.
   Look for `logger.error("Error loading/parsing file for {sym}...")` in server logs.
   For NAS100: file must be `USTEC.parquet`, not `NAS100.parquet`.

2. **Was SL distance zero?**
   → `utils/mfe_calculator.py` — early return before walk
   If `entry_price == stoploss_price`, the walk aborts immediately with `_empty_result()`.

3. **Did the calculator raise an exception?**
   → Check server logs for `mfe_calculator` WARNING or ERROR lines.
   Any uncaught exception in `calculate_mfe()` is caught by the outer try/except, sets `price_path_captured=False`, and the trade is still saved with NULL fields.

4. **For pending orders: did the trigger candle exist?**
   → `utils/mfe_calculator.py` — pending order trigger block
   If no candle crosses `limit_price` before data ends or expiry fires, walk aborts.

---

### SYMPTOM: Trade result (pnl_r / outcome) is wrong

**This is always a walk engine bug.**

Check in this order:

1. **Is the pip size correct for this symbol?**
   → `utils/pip_utils.py :: get_pip_size()`
   Wrong pip size = wrong SL distance = wrong RR = wrong TP/SL threshold comparison.
   For XAUUSD verify 0.1. For NAS100 verify 1.0. For JPY pairs verify 0.01.

2. **Is the candle step order intact?**
   → `utils/mfe_calculator.py` — steps a through g inside the loop
   Order must be: elapsed → R milestones → dip → BE trigger → SL → TP → UNTP snapshot.
   If SL check (e) runs before BE trigger (d), BE can never activate. If TP check (f) runs
   before SL check (e), a candle that hits both SL and TP resolves as TP incorrectly.

3. **Did post-walk cleanup run?**
   → `utils/mfe_calculator.py` — after loop, before result dict construction
   If a wide candle hit dip AND TP in the same iteration, dip fields should be zeroed.
   If a wide candle hit BE AND TP in the same iteration, BE fields should be cleared.
   If these cleanups are missing or inside the loop, phantom BE/dip data appears.

4. **Is the UNTP stop condition correct?**
   → `utils/mfe_calculator.py` — UNTP state variables
   Check `be_triggered` ACTUAL value (not `breakeven_active` config).
   If BE was configured but TP fired first: `be_triggered=False` → UNTP stop = original SL.
   If UNTP is stopping at entry_price when it should stop at SL, `be_triggered` was set
   incorrectly.

5. **Is the trade type buy/sell handled correctly?**
   → `utils/mfe_calculator.py` — `base_trade` variable
   For sell trades: favourable direction is DOWN. Dip is price moving ABOVE entry.
   If a sell trade shows inverted MFE/MAE, the buy/sell direction logic is flipped.

---

### SYMPTOM: Channel streak is wrong

**This is a streak query or classification bug.**

Check in this order:

1. **Is the query ordered by entry_time, not saved_at?**
   → `utils/mfe_calculator.py :: _compute_streak()`
   Must be `ORDER BY entry_time DESC`. If `saved_at` is used, re-saving any trade
   moves it to position 0 of the streak window.

2. **Is hit_be being treated as a loss?**
   → `utils/mfe_calculator.py :: _compute_streak()`
   `hit_be` must hit the `continue` branch (skip). If it falls through to `sign = -1`,
   a 0R trade incorrectly breaks win streaks.

3. **Are open/none trades being counted?**
   → `utils/mfe_calculator.py :: _compute_streak()`
   `open` and `none` outcomes must also be skipped. Only `hit_tp` and `hit_sl` score.

4. **Is the streak at the right channel scope?**
   → `utils/mfe_calculator.py :: _compute_streak(channel_id)`
   The query must filter by `channel_id`. If the filter is missing, streak includes
   trades from all channels.

---

### SYMPTOM: Statistics win rate or net RR is wrong

**This is a classification or denominator bug in trade_statistics.py.**

Check in this order:

1. **Is price_path_captured filtering applied first?**
   → `utils/trade_statistics.py :: compute_overview()`
   Trades with `price_path_captured=False` must be in `excluded` list only.
   If they leak into `good`, they appear as inconclusive and dilute the denominator.

2. **Is the UNTP denominator using alive_at_Xh, not COUNT(*)?**
   → `utils/trade_statistics.py :: resolve_win_loss()`
   For `fixed_rr` / `fixed_pips` modes with a time limit, check `alive_val = trade.get(alive_col)`.
   If `alive_val` check is missing, trades where UNTP stopped before the checkpoint
   count as losses instead of inconclusive — this massively deflates win rate.

3. **Is hit_be classified correctly for the tp_mode?**
   → `utils/trade_statistics.py :: resolve_win_loss()`
   In `original_tp` mode: `hit_be` must return `'loss'` (not `'inconclusive'`).
   In `fixed_rr`/`fixed_pips` modes: classification is purely MFE-based.

4. **Is equity curve in correct chronological order?**
   → `routes/statistics_routes.py :: _load_trades()`
   Must use `ORDER BY entry_time ASC`. If the query is DESC, the equity curve runs
   backwards and max_drawdown is calculated against the wrong peak.

5. **Is tp_value being passed correctly for fixed_rr mode?**
   → `routes/statistics_routes.py :: statistics_overview()`
   `tp_value=None` with `tp_mode='fixed_rr'` causes every trade to resolve as
   inconclusive. Check the JSON payload from the browser to verify tp_value is present.

---

### SYMPTOM: Channel detail page crashes or drawer is empty/broken

**This is almost always a JavaScript issue in channel_detail.html.**

Check in this order:

1. **Is there a TDZ crash in renderDrawerContent()?**
   → `templates/channel_detail.html :: renderDrawerContent()`
   Open the browser console. A TDZ error reads: `Cannot access 'X' before initialization`.
   This means a `const` is being referenced before its declaration line.
   Fix: move the declaration BEFORE its first use, following the strict order:
   DAYS/streakVal/_outcome → _streakIsNeutral/streakDisplay → ref/_refMfe/_refMae/_refStopped
   → _dip/_advCandles → shapeName → metrics → refLabel → innerHTML.

2. **Is the trade data missing a field the drawer expects?**
   → `db.py :: Trade.to_dict()`
   If a new field was added to the model but not to `to_dict()`, the JS receives `undefined`
   for that field. `undefined` in arithmetic returns `NaN`, which then breaks all downstream
   metric display.

3. **Is the UNTP window selector returning the wrong column name?**
   → `templates/channel_detail.html` — window selector JS block
   The selector builds column names like `mfe_at_${key}_r`. If `key` doesn't match
   the exact CHECKPOINT_KEYS strings (`30min`, `1h`, `2h`, etc.), the lookup returns
   `undefined` and the drawer shows `--` for all UNTP metrics.

4. **Is the RR/Pips toggle broken?**
   → `templates/channel_detail.html` — `show-pips` CSS class on `<body>`
   If pip values are showing in RR mode or vice versa, check that the toggle button
   correctly adds/removes `show-pips` from `document.body.classList`.
   The toggle must NOT re-render the drawer — it is CSS-only.

5. **Is the page loading but the trades table empty?**
   → `routes/channel_routes.py :: channel_detail()`
   → `utils/trade_storage.py :: get_trades_by_channel()`
   Check the URL query params — an active filter (symbol, outcome, date) may be
   excluding all trades. Check server logs for any exception in the route handler.

---

### SYMPTOM: Trade save returns an error JSON

**Trace the save flow from the route inward.**

1. **`{success: false, error: "Missing required field: X"}`**
   → `routes/save_routes.py :: _parse_form()`
   A required field was empty in the POST body. Check the save modal JS to confirm
   all hidden inputs from `save_context` are present and non-empty.

2. **`{success: false, error: "Invalid channel selection."}`**
   → `routes/save_routes.py :: _get_or_create_channel()`
   `channel_id` was not a valid integer and wasn't `"new"`. Check the channel dropdown
   serialisation in results.html.

3. **`{success: false, error: "Cannot save to an archived channel."}`**
   → `routes/save_routes.py :: _get_or_create_channel()`
   Channel exists but `is_archived=True`. The dropdown should not show archived channels —
   check `list_channels_json()` which filters by `is_archived=False`.

4. **`{success: false, error: "An unexpected error occurred."}`**
   → Check server logs for the full traceback.
   Common causes: `KeyError` in Trade() constructor (a field missing from `_empty_result()`
   after a schema change), `IntegrityError` (null constraint on a new non-nullable column
   before migration), `DetachedInstanceError` (ORM attribute access after commit).

---

### SYMPTOM: Statistics page fails to load or returns empty results

**Diagnose in two parts: page load vs. API call.**

For page load failure (GET /statistics):
→ `routes/statistics_routes.py :: statistics_hub()`
Check server logs. The route queries `Trade.symbol` distinct — if the DB is empty or
`trades.db` doesn't exist, this query returns an empty list (no error). Verify the
DB file exists and trades are present.
Note: P4-GAP-1 — there is an undiagnosed page load issue. Check browser console
for JS errors before investigating Python.

For API failure (POST /statistics/overview):
1. Check the JSON payload being sent — `tp_mode`, `tp_value`, `channel_ids`.
2. `tp_mode='fixed_rr'` with `tp_value=None` or `tp_value <= 0` returns a 400 error.
3. If `channel_ids` is an empty list, ALL channels are included (intended behaviour).
4. Check server logs for exceptions in `compute_overview()`.

---

### SYMPTOM: Channel delete fails silently or throws FK error

→ `utils/trade_storage.py :: delete_channel()`

The bulk Trade delete must use `synchronize_session="fetch"` (BUG-1 fix). If this
parameter is missing, SQLAlchemy may leave stale Trade objects in the session, causing
the subsequent channel row deletion to fail with a foreign key constraint violation.

Also check the `force` flag parsing in `routes/channel_routes.py :: delete_channel_route()`.
The route accepts `force=true`, `force=1`, and `force=yes`. Old code only accepted `force=1`
(BUG-2 fix). If the frontend sends `"true"` and the backend only checks `== "1"`,
the force delete silently fails.

---

## SECTION 4 — CALCULATOR DEBUG STRATEGY

When a calculation result is wrong, follow this sequence:

**Step 1 — Confirm the symbol loaded**
Check that `symbol.upper()` is a key in `data_frames` at the start of `calculate_mfe()`.
If not: log shows `"Error loading/parsing file for {sym}"` at startup.
Fix: verify parquet file exists in `Stored files/` with correct name.
For NAS100: file must be `USTEC.parquet`. Key in data_frames is `"NAS100"`.

**Step 2 — Confirm pip size**
Add a temporary log: `logger.info("pip_size=%s for %s", pip_size, symbol)`.
Expected: XAUUSD=0.1, XAGUSD=0.01, NAS100/US30=1.0, USOIL/UKOIL=0.1, JPY=0.01, others=0.0001.
Wrong pip size means every RR calculation is wrong.

**Step 3 — Confirm entry candle**
For market orders: the walk starts at the candle matching `entry_time`.
For pending orders: the walk starts at the trigger candle, not entry_time.
Log `actual_entry_time` and `actual_entry_price` at the start of the loop.

**Step 4 — Trace the first resolution candle**
Add temporary logging inside the candle loop for the resolution condition that fires.
Check: which step (e=SL, f=TP, d=BE) triggered? What was the candle's High/Low/Close?
For buy trades: SL fires when `candle.Low <= current_sl`. TP fires when `candle.High >= takeprofit_price`.
For sell trades: SL fires when `candle.High >= current_sl`. TP fires when `candle.Low <= takeprofit_price`.

**Step 5 — Check post-walk cleanup**
After the loop, verify:
- Was `peak_dip_time` on the same candle as `resolution_candle_time`? If yes, dip should be zeroed.
- Was `be_trigger_min == resolution_min` AND `outcome == 'hit_tp'`? If yes, BE should be cleared.
These cleanups run AFTER the loop. If they're inside the loop or missing entirely, phantom data appears.

**Step 6 — Verify the result dict keys**
Check `_empty_result()` — every key in this dict must also appear in the final `result` dict.
If a key is in `_empty_result()` but missing from the `result` build, that field stores NULL
even for successful walks.

---

## SECTION 5 — DATABASE DEBUG STRATEGY

**Trade not saved / 500 on save**
→ Check server logs for the full exception traceback.
→ `routes/save_routes.py :: save_trade()` — the outer try/except logs all exceptions.
→ Most common: a new column was added to `Trade` model but not to the Trade() constructor in `save_routes.py`, causing a missing keyword argument error.

**Fields are NULL after successful save**
→ `price_path_captured=False` — see Symptom 1 above.
→ OR: a column exists in the model but is not assigned in the `result` dict in `mfe_calculator.py`.
→ Check `_empty_result()` matches the final `result` dict key-for-key.

**Schema change not taking effect**
→ `db.create_all()` does NOT add columns to existing tables. This is the most common
   "why isn't my new field saving?" issue.
→ Delete `trades.db` and re-run migration:
   `python3 -c "from app import app; from db import db; app.app_context().push(); db.drop_all(); db.create_all(); print('Done')"`
→ After migration: re-save all test trades from scratch. Existing rows are gone.

**to_dict() returning None for a field that has data**
→ `db.py :: Trade.to_dict()`
→ The field was added to the model but not added to the `to_dict()` return dict.
→ Result: statistics and JS both receive `None` for this field even when DB has a value.

**DetachedInstanceError after delete or move**
→ `utils/trade_storage.py :: delete_trade()` or `move_trade()`
→ `channel_id` or `new_channel_id` must be captured as a plain int BEFORE `db.session.commit()`.
→ After commit, SQLAlchemy expires all ORM attributes. Accessing `.channel_id` on a deleted
   Trade triggers a refresh that fails because the row no longer exists.

**Channel delete FK constraint error**
→ `utils/trade_storage.py :: delete_channel()`
→ Must use `synchronize_session="fetch"` in the bulk Trade delete.
→ Without it, stale Trade ORM objects remain in session when the Channel row is deleted.

---

## SECTION 6 — TEMPLATE DEBUG STRATEGY

**channel_detail.html — JS crash on drawer open**
1. Open browser DevTools console.
2. Look for `ReferenceError: Cannot access 'X' before initialization` — this is TDZ.
3. Find the `const X` declaration in `renderDrawerContent()`.
4. Find all places `X` is used in the function.
5. Move the declaration above the first use. Follow the strict order documented in AI_RULES.md Section 7.

**channel_detail.html — Drawer opens but shows -- for all metrics**
1. Console log the `trade` object passed to `renderDrawerContent(trade)`.
2. Check for `undefined` or `null` on the UNTP fields (`mfe_at_1h_r`, `alive_at_1h`, etc.).
3. If all UNTP fields are null: `price_path_captured` may be False, or DB was not migrated after Phase 1 UNTP schema changes (PENDING-1).
4. If only the selected window fields are null: the window selector key doesn't match a CHECKPOINT_KEY. Check the key string (`30min`, `1h`, `2h`, `4h`, `8h`, `12h`, `24h`, `48h`, `72h`, `120h`, `168h`, `240h`, `336h`, `504h`).

**channel_detail.html — MFE:MAE ratio wrong**
→ For `hit_tp` trades: denominator must be `t.mae_r` (trade walk MAE, frozen at close).
   Never use `_refMae` for hit_tp — UNTP continues past close and accumulates additional MAE.
→ For `hit_sl` / `hit_be` trades: use `_refMae` (UNTP MAE — same value since UNTP stopped same candle).

**statistics.html — Charts not rendering**
1. Check browser console for JS errors.
2. Check the network tab for the POST /statistics/overview response.
3. If the response is a 400 or 500 JSON error, trace to the route handler.
4. If the response is valid JSON but charts don't render, the issue is in the chart initialisation JS in statistics.html.
5. Note P4-GAP-1 — there is an undiagnosed statistics page load issue. Console errors are the first place to look.

**results.html — Save modal dropdown empty**
→ The modal fetches `/channels/list_json` on open.
→ Check browser network tab for the fetch response.
→ If it returns `[]`: no non-archived channels exist. Create one first.
→ If the fetch fails: check `routes/save_routes.py :: list_channels_json()` for errors.

---

## SECTION 7 — DATA SOURCE DEBUGGING

**Parquet file missing or not loading**
1. Check server startup logs for `"Error loading/parsing file for {sym}"`.
2. Verify the file exists: `Stored files/{SYMBOL}.parquet` in the project root.
3. For NAS100: the file must be `Stored files/USTEC.parquet`. The key in `data_frames` is `"NAS100"`.
4. Check `data_loader.py` — it uses `trade_calculations.get_file_name(sym)` to resolve filenames.
   `FILE_NAME_MAPPING = {"NAS100": "USTEC"}` in `utils/trade_calculations.py`.

**Symbol in SYMBOLS list but data not loading**
→ `data_loader.py` logs `logger.error(...)` per symbol on failure but does not raise.
→ The app starts successfully even if some symbols fail to load.
→ For a failed symbol: `data_frames` simply won't have that key. Any trade save attempt
   for that symbol returns `price_path_captured=False` immediately.

**Timestamp mismatch — walk starts at wrong candle**
→ `data_loader.py` parses `Local time` with format `%d.%m.%Y %H:%M:%S` (day.month.year).
→ If a parquet file uses a different datetime format, `pd.to_datetime(..., errors='coerce')`
   silently produces NaT, those rows are dropped, and the candle for `entry_time` may not exist.
→ Check: `df['Local time'].isna().sum()` — high NaT count = format mismatch.

**Correct symbol but wrong price data**
→ `data_frames` keys are always uppercase: `data_frames["EURUSD"]`, `data_frames["XAUUSD"]`.
→ In `mfe_calculator.py`, the symbol is normalised via `sym_key = symbol.upper()` before lookup.
→ If a symbol loads from the wrong file (very unlikely but possible if filenames are reused),
   check `Stored files/` for duplicate or misnamed files.

**Data ends before trade resolution**
→ When the candle loop exhausts all available data without hitting TP/SL/BE:
   `outcome = 'open'` (if TP was set) or `'none'` (if no TP).
   `pnl_r = NULL`. `price_path_captured = True`.
→ This is not a bug — it means the trade is still theoretically open in the dataset.
→ If this is unexpected, check the parquet file's date range against the trade's entry_time.

---

## SECTION 8 — FAST DEBUG CHECKLIST

Copy this checklist at the start of any debugging session.

```
PRE-DIAGNOSIS
□ Read the symptom carefully — which layer is failing? (save / walk / display / stats)
□ Check server logs first — many bugs produce an explicit error line
□ Check browser console for JS errors before opening Python files

CALCULATION BUG
□ Confirm symbol is in data_frames (check startup logs)
□ Confirm pip size: get_pip_size(symbol) in pip_utils.py
□ Confirm entry candle: actual_entry_time and actual_entry_price
□ Confirm candle step order: a(elapsed) → b(milestones) → c(dip) → d(BE) → e(SL) → f(TP) → g(snapshot)
□ Confirm post-walk cleanup runs AFTER loop: dip phantom + BE phantom
□ Confirm pnl_r assigned in Section 9 only, from outcome branch — not from MFE fields
□ Confirm _empty_result() keys match result dict keys

DATABASE BUG
□ Was db migrated after the last schema change? (create_all ≠ migration)
□ Is the new field in Trade.to_dict()?
□ Is the new field in save_routes Trade() constructor?
□ Is the new field key in mfe_calculator _empty_result()?
□ For delete/move: is channel_id captured before commit?

STATISTICS BUG
□ Are price_path_captured=False trades excluded first?
□ Is UNTP denominator alive_at_Xh=True (not COUNT(*))?
□ Is hit_be = loss in original_tp mode?
□ Is hit_be = skip in streak (not loss)?
□ Is equity curve ordered by entry_time ASC?

TEMPLATE BUG
□ Open browser console — any TDZ or ReferenceError?
□ Log the trade object passed to renderDrawerContent — any undefined fields?
□ Is the UNTP window selector key exactly matching a CHECKPOINT_KEY string?
□ For MFE:MAE: hit_tp uses t.mae_r, others use _refMae?
□ Is the RR/Pips toggle using CSS class only (not re-rendering)?

STREAK BUG
□ Is _compute_streak ordering by entry_time DESC (not saved_at)?
□ Is hit_be hitting the continue branch (skip)?
□ Is the channel_id filter applied in the streak query?

DATA SOURCE BUG
□ Does Stored files/{SYMBOL}.parquet exist?
□ For NAS100: does Stored files/USTEC.parquet exist?
□ Are Local time timestamps parsing correctly (format %d.%m.%Y %H:%M:%S)?
□ Does the parquet date range cover the trade's entry_time?
```

---

