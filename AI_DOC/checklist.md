# Backtrack — Verification Checklist

# Systematic checks per phase. Covers correctness, edge cases, and regressions.

# Phase statuses in MCP.md. Architecture rules in Backtest_Architecture.md.

# Last updated: 2026-03-15

# HOW TO USE:
# [ ] = not verified  [x] = verified manually  [!] = failed / issue found
# [V] = verified by Claude code trace (no app run needed)
# [N/A] = not applicable (feature removed or superseded)
# Manual checks: require running the app with real trade data.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PREREQUISITE — DB MIGRATION ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[x] PENDING-1  DB migration COMPLETE — confirmed 2026-03-14.
               trades.db dropped and recreated. All UNTP columns + untp_notes present.
               No action required.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 1 — SAVE TRADE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── Setup ───────────────────────────────────────────────────────
[x] S1  pip install -r requirements.txt runs without errors
[x] S2  python app.py starts, no errors in terminal
[x] S3  / route loads monitor form with symbol dropdown populated

── Monitor + Save Flow ─────────────────────────────────────────
[x] M1  Monitor run completes, results.html loads with outcome
[V] M2  "💾 Save Trade" button visible in results.html
[V] M3  Clicking Save opens modal
[V] M4  Escape key closes modal without saving
[V] M5  Channel dropdown shows existing channels
[V] M6  "Create new channel" option revealed when selected
[V] M7  Empty channel name shows validation error
[V] M8  Saving to new channel creates the channel
[V] M9  Toast message appears on success
[V] M10 Toast warning appears when price_path_captured=False

── Field Correctness ───────────────────────────────────────────
[x] F1  entry_time stored correctly (matches form input)
[x] F2  entry_price = closing price at entry_time for market orders
[V] F3  entry_price = limit_price for pending orders
[V] F4  stoploss_price / takeprofit_price stored correctly
[V] F5  tp_rr_target computed correctly from prices and SL distance
[V] F6  sl_distance_pips correct for each symbol type (use pip_utils values)
[V] F7  pnl_r = +tp_rr_target for hit_tp trades
[V] F8  pnl_r = -1.0 for hit_sl trades
[V] F9  pnl_r = 0.0 for hit_be trades
[V] F10 pnl_r = NULL for open/none trades
[V] F11 outcome_at_user_tp is one of: hit_tp / hit_sl / hit_be / open / none
[V] F12 exit_price = takeprofit_price for hit_tp
[V] F13 exit_price = stoploss_price for hit_sl
[V] F14 exit_price = entry_price for hit_be
[V] F15 exit_price = last candle close for open/none
[V] F16 mfe_pips and mfe_r > 0 for any trade that moved in favour
[V] F17 mae_r > 0 for any trade that moved against (even briefly)
[N/A] F18 retracement_from_mfe_r — stored correctly, not displayed. Not a bug.
[V] F19 time_to_resolution_minutes > 0 for resolved trades
[V] F20 price_path_captured = True for normal trades
[V] F21 entry_session populated correctly based on entry_hour
[V] F22 entry_day_of_week = 0 for Monday, 4 for Friday

── UNTP Snapshots ──────────────────────────────────────────────
[V] U1  All 56 UNTP columns populated (non-null) for normal trades
[V] U2  alive_at_30min = True for a trade that resolved after 30min
[V] U3  alive_at_30min = False for a trade that resolved before 30min
[V] U4  mfe_at_Xh_r increases or stays same as X increases (UNTP running)
[V] U5  mfe_at_Xh_r frozen (constant) after UNTP stops
[V] U6  outcome_at_Xh = 'still_open' before trade close checkpoint
[V] U7  outcome_at_Xh = 'hit_tp'/'hit_sl'/'hit_be' after trade close
[V] U8  alive_at_Xh = True can coexist with outcome_at_Xh = 'hit_tp'
[V] U9  All 14 checkpoints after trade close show correct frozen outcome

── mfe_path_json ───────────────────────────────────────────────
[V] P1  mfe_path_json is valid JSON, array of 4-element arrays
[V] P2  Sampling intervals are multiples of 15 (15, 30, 45 … not drifting)
[V] P3  untp_alive = 1 while UNTP running, 0 after stop
[V] P4  Forced entry exists at trade close elapsed_min
[V] P5  Forced entry exists at UNTP stop elapsed_min
[V] P6  No duplicate elapsed_min entries

── Streak ──────────────────────────────────────────────────────
[V] K1  After first trade: channel_streak_at_save correct sign
[V] K2  Consecutive wins: streak increments +1 each time
[V] K3  Consecutive losses: streak decrements -1 each time
[V] K4  hit_be after a win streak: streak unchanged (hit_be = skip)
[V] K5  hit_tp after hit_be after hit_tp: streak continues from pre-be value
[V] K6  Re-saving a trade: does NOT change streak ordering (uses entry_time)

── CSV Export ──────────────────────────────────────────────────
[V] CSV1 All 56 UNTP columns present in _CSV_COLUMNS
          Confirmed in trade_storage.py. P2-GAP-1 CLOSED.
[V] CSV2 mfe_path_json present in _CSV_COLUMNS
          Confirmed in trade_storage.py. P2-GAP-1 CLOSED.

── Move Trade Streak ────────────────────────────────────────────
[V] MV1 move_trade() calls _recompute_channel_streaks() for source channel
[V] MV2 move_trade() calls _recompute_channel_streaks() for destination channel
[V] MV3 _recompute_channel_streaks() uses entry_time ASC (correct order)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 2 — CHANNEL UI + DRAWER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── Channel List ────────────────────────────────────────────────
[V] C1  /channels loads, shows all non-archived channels
[V] C2  Each channel card shows trade count, win rate, net R
[V] C3  "Show archived" toggle shows/hides archived channels
[V] C4  Creating channel: name required, empty name shows error
[V] C5  Duplicate channel name shows error
[V] C6  Rename: new name reflected immediately
[V] C7  Archive: channel moves to archived list
[V] C8  Delete: channel and all its trades are deleted
[V] C9  Delete archived channel: works correctly

── Channel Detail ──────────────────────────────────────────────
[V] D1  /channels/<id> loads, table shows all trades for that channel
[V] D2  PnL summary bar: net R = sum of pnl_r (not derived from MFE)
[V] D3  PnL summary bar: win rate excludes price_path_captured=False trades
[V] D4  PnL summary bar: excluded count shown when > 0
[V] D5  Table row click opens drawer from right
[V] D6  Esc key closes drawer
[V] D7  Overlay click closes drawer
[V] D8  <- -> keyboard nav steps through trades while drawer open
[V] D9  RR/Pips toggle pill changes all RR displays in drawer and table
[V] D10 RR/Pips toggle persists across drawer opens in same session

── Trade Detail Drawer ─────────────────────────────────────────
[V] DR1  Outcome label correct (hit_tp / hit_sl / hit_be / open / none)
[V] DR2  pnl_r shown correctly for all outcome types
[V] DR3  Trade shape label correct
[N/A] DR4  MFE window selector removed in Phase 4 Module 2 rewrite.
[V] DR5  Max mode: uses highest mfe_at_Xh_r where alive=True
[V] DR6  Max mode fallback: uses t.mfe_r if all alive flags false/null
[N/A] DR7  Checkpoint selector removed.
[V] DR8  MFE:MAE ratio denominator = t.mae_r for hit_tp trades
[V] DR9  MFE:MAE ratio denominator = refMae for hit_sl/hit_be trades
[V] DR10 Streak display: hit_be shows "(prior, not counted)" label
[V] DR11 Streak display: open/none shows "(prior, not counted)" label
[V] DR12 No TDZ crash when opening drawer (const _outcome declared before use)
[V] DR13 Notes field: inline edit saves via AJAX, updates without page reload
[V] DR14 Trade with no TP set: drawer handles null takeprofit_price gracefully

── Trade Operations ────────────────────────────────────────────
[V] TO1 Delete trade: trade removed from table without page reload
[V] TO2 Move trade: trade appears in destination channel
[V] TO3 Move trade: source channel trade count decremented in UI
[V] TO4 CSV export: downloads file with correct columns
[V] TO5 CSV export: price_path_captured field included

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 3 — EDGE CASES (all verified by test suite) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── Pending Orders ──────────────────────────────────────────────
[V] EC1a Limit order: entry triggered on candle where low ≤ limit (buy) or high ≥ limit (sell)
[V] EC1b Limit order never triggers: price_path_captured=False, all numeric fields NULL
[V] EC1c Stop buy: triggered on candle where high ≥ stop level AND prev_close was below stop
[V] EC1d Pending order expires before trigger: outcome=none/open correctly
[V] EC1e Pending trigger on very last candle in parquet: graceful fail

── Data Boundary ───────────────────────────────────────────────
[V] EC2a Symbol not in data_frames dict: ValueError caught, price_path_captured=False
[V] EC2b No candles after entry/trigger time: price_path_captured=False
[V] EC2c Parquet data ends before trade resolves: outcome=open or none
[V] EC2d SL distance = 0: ValueError raised before walk starts

── Breakeven Logic ─────────────────────────────────────────────
[V] EC4a BE configured, price reaches BE level: breakeven_triggered=True
[V] EC4b BE configured, TP fires before BE level: breakeven_triggered=False. All BE fields NULL.
[V] EC4c BE configured at very high R (7R): only triggers if price actually reaches level
[V] EC4d Wide candle: BE level AND TP same candle. Post-walk cleanup fires. BE fields cleared.
[V] EC4e After BE triggered: SL check uses entry_price, not stoploss_price
[V] EC4f mfe_after_be_r: accumulates from BE activation until TRADE CLOSE only.

── Dip Logic ───────────────────────────────────────────────────
[V] EC5a BUY dip: adverse move is price BELOW entry_price
[V] EC5b SELL dip: adverse move is price ABOVE entry_price
[V] EC5c Wide candle: dip recorded AND TP fires same candle. Post-walk cleanup zeros dip.
[V] EC5d Trade that dips then runs to TP: dip_occurred=True AND outcome=hit_tp

── UNTP Walk ───────────────────────────────────────────────────
[V] EC6a be_triggered=False: UNTP stops when original stoploss_price is hit
[V] EC6b be_triggered=True: UNTP stops when entry_price is retraced
[V] EC6c hit_sl trade: UNTP and trade stop same candle. Checkpoints frozen.
[V] EC6d hit_be trade: same as hit_sl — UNTP and trade stop same candle.
[V] EC6e hit_tp trade: UNTP continues. Can have alive=True after trade close.
[V] EC6f UNTP reaches 504h without hitting stop: alive_at_504h=True.
[V] EC6g UNTP MFE/MAE frozen at stop candle: no further updates.

── mfe_path_json ───────────────────────────────────────────────
[V] EC7a Sampling uses last_path_min += 15, not = elapsed_min.
[V] EC7b Forced entry at trade close: always present
[V] EC7c Forced entry at UNTP stop: always present
[V] EC7d Duplicate elapsed_min entries are deduplicated
[V] EC7e After UNTP stop: untp_alive = 0 in subsequent entries
[V] EC7f Trade that closes and UNTP stops same candle: single entry

── R Milestones ────────────────────────────────────────────────
[V] EC8a time_to_1r_minutes > 0 if price reached 1R during trade walk
[V] EC8b time_to_1r_minutes = NULL if price never reached 1R
[V] EC8c For hit_sl: time_to_2r_minutes = NULL if TP was 1.5R
[V] EC8d R milestone timestamps are monotonically non-decreasing

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 4 — STATISTICS MODULE 1 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[x] ST1  /statistics page loads without console JS errors
[V] ST2  Channel selector populates with all non-archived channels
[V] ST3  "All channels" option works correctly
[V] ST4  TP mode: original_tp returns win count from outcome='hit_tp' only
[V] ST5  TP mode: fixed_tp computes against mfe_r >= target
[V] ST6  Time limit = none: denominator = all trades with price_path_captured=True
[V] ST7  fixed_untp: win = mfe_at_Xh_r >= target (alive irrelevant)
[x] ST8  Different time limits give different win rates (verify with real data)
[V] ST9  Net RR = sum of pnl_r for included trades (not derived from anything else)
[V] ST10 price_path_captured=False trades: excluded from counts AND not shown in net RR
[V] ST11 Excluded count displayed when > 0
[N/A] ST12 RETIRED — old UNTP alive gate rule, superseded by BUG-16 fix
[V] ST13 hit_be in original_tp mode: counted as loss (not skip)
[N/A] ST14 RETIRED — old rule said "hit_be counted as win if alive=True". Superseded.
           Correct rule: win = mfe_at_Xh_r >= target regardless of alive (BUG-16).
[V] ST15 Date filter: date_to is inclusive of the selected day
[V] ST16 Symbol filter: "all" returns all symbols; specific symbol filters correctly
[V] ST17 Trade type filter: individual types routed via else branch in _load_trades()
[x] ST18 Trade direction UI: 7 options visible (All/Buy/Sell/Limit Buy/Limit Sell/Stop Buy/Stop Sell)
[ ] ST19 Selecting "Limit Buy" in statistics filters to limit_buy trades only
          MANUAL — verify with real trades

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 4 — MODULE 2: UNTP DUAL-SECTION VIEW [DELIVERED 2026-03-13] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── Pre-flight ──────────────────────────────────────────────────
[x] UV0a Run DB migration (drop/recreate trades.db) for untp_notes column
[x] UV0b Verify trades.db has untp_notes column after migration

── Page Toggle ─────────────────────────────────────────────────
[V] UV1  TP View toggle shows TP table, hides UNTP section
[V] UV2  UNTP View toggle shows UNTP section, hides TP table
[V] UV3  Default view on page load is TP View

── UNTP Window Controls ────────────────────────────────────────
[V] UV4  Slider snap: index 0=30min, 13=504h, 14 checkpoints total
[V] UV5  Numeric input accepts arbitrary minutes; slider snaps to nearest CP
[V] UV6  Slider and numeric input stay in sync bidirectionally
[V] UV7  Resolved label shows nearest checkpoint name + duration

── UNTP PnL Bar ────────────────────────────────────────────────
[V] UV8  Running/Loss(SL)/BE counts correct at each window
[V] UV9  alive=true → Running regardless of MFE sign (positive or negative)
[V] UV10 alive=false + be_triggered=true → BE (0.0R)
[V] UV11 alive=false + be_triggered=false → Loss (-1.0R)
[V] UV12 Net R = sum of all provisional PnLs
[V] UV13 Changing window updates PnL bar counts correctly

── UNTP Table ──────────────────────────────────────────────────
[V] UV14 UNTP table rows open UNTP drawer (not TP drawer)
[V] UV15 price_path_captured=false trades excluded from UNTP table
[V] UV16 MFE@window and MAE@window update when window changes
[V] UV17 Peak MFE column shows highest mfe across all alive checkpoints

── UNTP Drawer ─────────────────────────────────────────────────
[V] UV18 UNTP drawer is separate HTML element (#untpDrawer vs #tradeDrawer)
[V] UV19 Escape key closes untpDrawer, not tradeDrawer
[V] UV20 UNTP overlay click closes UNTP drawer
[V] UV21 Peak MFE = highest mfe_at_Xh_r where alive_at_Xh=True
[V] UV22 Alive Until = last checkpoint where alive=True
[V] UV23 MFE Capture = untpPnl / peak x 100
[V] UV24 MAE Pressure = maeAtWindow x 100 (% of 1R SL)
[V] UV25 UNTP Notes save to /trades/<id>/untp-notes -> untp_notes column
[V] UV26 TP drawer notes unchanged (still /trades/<id>/notes -> notes column)
[V] UV27 R/Pips toggle rerenders UNTP table and open UNTP drawer

── Edge Cases ──────────────────────────────────────────────────
[V] UV28 mfe_path_json=null -> falls back to nearest checkpoint gracefully
[V] UV29 All alive=false -> no Running trades in PnL bar
[V] UV30 No trades with price data -> shows "No trades" message in UNTP table
[V] UV31 Window=0 (before any candle) -> graceful empty state

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 4 — STATISTICS REDESIGN: 4-MODE SYSTEM [DELIVERED 2026-03-15] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── Mode Switching ──────────────────────────────────────────────
[ ] SR1  original_tp selected: time limit select disabled and visually greyed
[ ] SR2  fixed_tp selected: time limit select disabled and visually greyed
[ ] SR3  fixed_untp selected: time limit select enabled and active
[ ] SR4  untp_overview selected: time limit select enabled and active
[ ] SR5  R/Pips pill toggle: visible only for fixed_tp and fixed_untp
[ ] SR6  R/Pips pill toggle: hidden for original_tp and untp_overview
[ ] SR7  Switching between fixed_tp and fixed_untp: pill toggle state preserved
[ ] SR8  Server enforces time_limit_hours=None for original_tp and fixed_tp

── original_tp ─────────────────────────────────────────────────
[ ] SR9  Win = outcome_at_user_tp='hit_tp' only
[ ] SR10 hit_be = loss (original_tp mode rule — R7)
[ ] SR11 Time limit has zero effect even if accidentally sent (server enforces)

── fixed_tp ────────────────────────────────────────────────────
[ ] SR12 R mode: win = mfe_r >= tp_value (trade walk peak, no UNTP)
[ ] SR13 Pips mode: win = mfe_r >= tp_value / sl_distance_pips
[ ] SR14 Denominator = all price_path_captured=True trades
[ ] SR15 Time limit has zero effect (server forces None)

── fixed_untp (Phase 4/5 — stored snapshot; Phase 6 upgrades to parquet re-walk) ──
[ ] SR16 R mode: win = mfe_at_Xh_r >= tp_value (alive_at_Xh irrelevant — BUG-16)
[ ] SR17 Pips mode: win = mfe_at_Xh_r >= (tp_value / sl_distance_pips)
[ ] SR18 Denominator = all price_path_captured=True with non-null mfe_at_Xh_r
[V] SR18b Trade where alive=False but mfe_at_Xh_r >= target counts as WIN
[V] SR18c Trade where alive=True but mfe_at_Xh_r < target counts as LOSS

── untp_overview (Phase 4/5 — stored snapshot; Phase 6 upgrades to parquet re-walk) ──
[ ] SR20 Two groups: BE On (stats_be_on) / BE Off (stats_be_off) shown side by side
[ ] SR21 Per group: Open count, SL count, BE count
[ ] SR22 Per group: Net R = sum(open mfe) + sl(-1.0) + be(0.0)
[ ] SR23 Per group: avg peak MFE (Open trades at window)
[ ] SR24 Per group: avg MAE (Open trades at window)
[ ] SR25 No win rate shown — consistent with DECISION-12
[ ] SR26 Time limit required — same enforcement as fixed_untp
[ ] SR27 Group with zero trades: no crash, no division error
[ ] SR28 Trades with price_path_captured=False excluded

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ REGRESSION CHECKS — run after any change to mfe_calculator.py ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[V] R1  pnl_r not derived from MFE or outcome strings
[V] R2  Streak still uses entry_time ORDER BY (not saved_at)
[V] R3  hit_be still = skip in streak (not loss)
[V] R4  mfe_path still uses += 15 (not = elapsed_min)
[V] R5  Post-walk cleanup still fires AFTER loop (not inside)
[V] R6  UNTP stop condition still checks be_triggered ACTUAL value
[V] R7  pip_utils.get_pip_size() still called for all pip calculations
[V] R8  No hardcoded pip sizes anywhere in mfe_calculator.py
[V] R9  price_path_captured=False returned on any exception (never crashes)
[V] R10 UNTP MFE/MAE frozen at stop candle and backfilled immediately

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ REGRESSION CHECKS — run after any change to channel_detail.html ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[V] J1  No new const added before _outcome declaration
[V] J2  No forward reference to any const declared later in renderDrawerContent
[V] J3  MFE:MAE denominator = t.mae_r for hit_tp (not UNTP mae)
[V] J4  hit_be / open / none streak display shows "(prior, not counted)"
[V] J5  UNTP window selector Max mode uses highest mfe where alive=True
[V] J6  Fallback to t.mfe_r when all alive flags are false/null
[V] J7  show-pips class on body triggers pip display (not RR)
[V] J8  UNTP drawer Escape handler targets #untpDrawer (not #tradeDrawer)
[V] J9  resolveUntpAtWindow: exact CP → path walk → nearest CP fallback
[V] J10 classifyUntpTrade: alive=true → Running regardless of MFE sign

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 5 — MODULE 2 (HIT RATE) + MODULE 7 (PNL REPORT) [COMPLETE] ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── Module 2 — Hit Rate ─────────────────────────────────────────
HR1  [V] — original_tp: hit_tp = win
HR2  [V] — original_tp: hit_sl/hit_be = loss
HR3  [V] — fixed_tp: mfe_r >= rr_target = win
HR4  [V] — pips unit: tp_value / sl_distance_pips
HR5  [V] — fixed_untp: mfe_at_Xh_r >= target = win
HR6  [V] — fixed_untp: alive_col never read — alive irrelevant (BUG-16)
HR7  [V] — fixed_untp: mfe_val is None → inconclusive
HR8  [V] — untp_overview: returns open/sl/be; win_rate=None
HR9  [V] — one row per distinct symbol
HR10 [V] — one row per distinct trade_type
HR11 [V] — session labels: all 5 sessions covered
HR12 [V] — day-of-week: weekend/None trades excluded
HR13 [V] — row has wins/losses/inconclusive/win_rate/net_rr
HR14 [V] — sorted by count desc; dow uses fixed Mon→Fri order
HR15 [V] — price_path_captured=False excluded per row
HR16 [V] — denominator = wins + losses (no alive filter)
HR17 [V] — inconclusive excluded from denominator
HR18 [V] — win_rate = None when evaluated=0; JS shows '—'
HR19 [V] — same payload sent to both /overview and /hitrate

── Module 7 — PnL Report ───────────────────────────────────────
[V] PR1  Equity curve = cumulative pnl_r, entry_time ASC
[V] PR2  open/none (pnl_r=NULL) excluded
[V] PR3  hit_be (pnl_r=0.0) = flat step on equity curve
[V] PR4  price_path_captured=False excluded
[V] PR5  Weekly totals = sum pnl_r per ISO week
[V] PR6  Monthly totals = sum pnl_r per month
[V] PR7  Weekly totals sum to monthly total (no double-counting)
[V] PR8  Zero-trade weeks shown as 0.0, not omitted
[V] PR9  Period boundaries use entry_time, not saved_at
[V] PR10 Per-symbol net RR = sum pnl_r for symbol
[V] PR11 Sum of per-symbol net RR = overall net RR
[V] PR12 Symbols sorted by net RR descending
[V] PR13 Zero-count symbols excluded
[V] PR14 Win streak = consecutive hit_tp (entry_time order)
[V] PR15 Loss streak = consecutive hit_sl
[V] PR16 hit_be = skip (not counted, not streak-breaking)
[V] PR17 open/none = skip
[V] PR18 Streak rules match R5/R6
[V] PR19 Zero trades: no crash, all totals 0.0
[V] PR20 Single trade: equity has 1 point, streak = 1 or 0
[V] PR21 All hit_be: net RR = 0.0, streaks = 0
[V] PR22 Date range: only trades in range appear

[V] fixed_untp: alive=False + mfe_at_Xh_r >= target = WIN
[V] fixed_untp: alive=True + mfe_at_Xh_r < target = LOSS
[V] fixed_untp: mfe_at_Xh_r=None → inconclusive

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ PHASE 6 — FULL SIMULATOR SUITE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── Shared Walk Engine (walk_engine.py) ─────────────────────────
[ ] WE1  walk_trade_untp() uses data_frames dict — zero disk reads
[ ] WE2  Stop reason 'sl': original SL hit (stoploss_price breached)
[ ] WE3  Stop reason 'be': BE triggered at be_trigger_r, then entry retraced
[ ] WE4  Stop reason 'time_limit': max_minutes reached before natural stop
[ ] WE5  Stop reason 'open': parquet data exhausted before any stop fires
[ ] WE6  WalkDataError raised when entry candle not in parquet
[ ] WE7  504h cap enforced regardless of max_minutes value
[ ] WE8  be_active=False: BE logic never applied, stop_reason never 'be'
[ ] WE9  be_active=True: BE triggers at user-supplied be_trigger_r, not trade's saved config
[ ] WE10 path output: [[elapsed_min, mfe_r, mae_r], ...] every candle from entry
[ ] WE11 No DB writes ever (R3)
[ ] WE12 Performance warning shown at >100 trades, confirm required at >300

── M1 fixed_untp Upgrade (parquet re-walk) ──────────────────────
[ ] FU1  Route calls walk_trade_untp() — no longer reads mfe_at_Xh_r stored column
[ ] FU2  Returns stats_be_on and stats_be_off (not stats_all/stats_be_active/stats_no_be)
[ ] FU3  BE on walk uses user-supplied be_trigger_r — not trade's saved breakeven config
[ ] FU4  Win = peak_mfe_r >= target; Loss = peak_mfe_r < target
[ ] FU5  "No limit" time option maps to max_minutes=30240 (504h cap)
[ ] FU6  Open trades (stop_reason='open') included — peak_mfe from available data
[ ] FU7  WalkDataError trades excluded; count shown as excluded_count
[ ] FU8  Response shape unchanged — frontend renderOverview() needs no changes

── M1 untp_overview Upgrade (parquet re-walk) ───────────────────
[ ] UO1  Route calls walk_trade_untp() — no longer reads alive_at_Xh stored column
[ ] UO2  Returns stats_be_on and stats_be_off
[ ] UO3  Open bucket = stop_reason in ('time_limit', 'open')
[ ] UO4  SL bucket = stop_reason == 'sl'
[ ] UO5  BE bucket = stop_reason == 'be' (only in BE on walk; never in BE off walk)
[ ] UO6  BE off walk: stop_reason never 'be' — all trades are SL or Open
[ ] UO7  "No limit" maps to max_minutes=30240
[ ] UO8  Old sidebar BE toggle (All/BE Active/No BE) removed from statistics.html

── M1 UI Changes ────────────────────────────────────────────────
[ ] UI1  BE On / BE Off / Difference buttons appear in results area after run
[ ] UI2  BE On button renders stats_be_on group
[ ] UI3  BE Off button renders stats_be_off group
[ ] UI4  Difference button opens drawer-style comparison page
[ ] UI5  Time limit dropdown includes "No limit" at top
[ ] UI6  BE Simulation: radio buttons (BE On / BE Off) + be_trigger_r input field
[ ] UI7  be_trigger_r field visible only when BE On selected
[ ] UI8  Switching BE On/Off re-renders from cached response — no server re-fetch

── M3 RR Sweep (stats_m3_sweep.html) ────────────────────────────
[ ] SW1  Server runs walk_trade_untp() once per trade per request
[ ] SW2  Request specifies be_active and be_trigger_r (if active)
[ ] SW3  Response per trade: trade_id, entry_time, session, path [[min, mfe, mae], ...]
[ ] SW4  Client holds path array permanently — no re-fetch on slider move
[ ] SW5  peak_mfe = max(mfe_r for path points where elapsed_min <= time_limit)
[ ] SW6  peak_mae = max(mae_r for path points where elapsed_min <= time_limit)
[ ] SW7  Win = peak_mfe >= target; Loss = peak_mfe < target; denominator = all trades
[ ] SW8  Adaptive steps: 0.25R up to 3R, 0.50R up to 6R, 1.00R beyond
[ ] SW9  Upper bound = max peak_mfe across all trades, rounded up to step
[ ] SW10 Time limit slider updates all rows instantly (client-side only)
[ ] SW11 Session filter updates rows instantly (client-side only)
[ ] SW12 Switching BE On/Off triggers new server request; result cached per mode
[ ] SW13 EV = (win_rate × target) + (loss_rate × -1.0)
[ ] SW14 Avg MAE before target: wins only, max(mae) in path up to first target hit
[ ] SW15 MAE:Target ratio = avg_mae_before / target
[ ] SW16 Median time-to-target: wins only, median elapsed_min when mfe first crossed target
[ ] SW17 Max consecutive losses in entry_time order (R5 rule — hit_be=skip)
[ ] SW18 Early exit %: wins where 75% of target hit within first 25% of time limit
[ ] SW19 Confidence: Red <20 / Yellow 20-49 / Green 50+
[ ] SW20 Best EV row marked ★
[ ] SW21 Best risk-adjusted = EV / (max_consec_losses + 1), marked ◆
[ ] SW22 Dead zone rows (EV < 0) visually greyed
[ ] SW23 BE On / BE Off / Difference buttons visible in results area after run
[ ] SW24 Difference page shows per-target: win rate change, EV change, net R change

── M4 BE Comparison (stats_m4_becompare.html) ───────────────────
[ ] BE1  All price_path_captured=True trades included (not filtered by saved BE state)
[ ] BE2  Group A: fresh re-walk with be_active=True, user's be_trigger_r
[ ] BE3  Group B: fresh re-walk with be_active=False, SL only
[ ] BE4  be_trigger_r always required for this module
[ ] BE5  Per group: open count, sl count, be count, avg peak MFE, avg peak MAE, net R, max consec stops
[ ] BE6  BE count always 0 in Group B (no stop_reason='be' possible)
[ ] BE7  Difference column shows Group B - Group A per metric
[ ] BE8  UI: BE On / BE Off / Difference drawer-style pages
[ ] BE9  Empty state handled (0 trades after filter — no crash)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ KNOWN ISSUES TRACKER ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BLOCKING:
  None.

CLOSED:
[x] PENDING-1  DB migration complete 2026-03-14.
[x] P2-GAP-1   _CSV_COLUMNS fixed 2026-03-15 (BUG-17). All 56 UNTP columns + mfe_path_json present.
[x] P2-GAP-2   move_trade streak recalc already implemented. Closed 2026-03-14.
[x] P4-GAP-1   /statistics page confirmed clean 2026-03-14.
[x] P5-PREREQ-1  CLOSED 2026-03-15. 4-mode redesign delivered.
[x] STATS-LOGIC-1  fixed_untp logic corrected (BUG-16). CLOSED 2026-03-15.
[x] TEST-14-UPDATE  test_14 fully updated (BUG-18). CLOSED 2026-03-15.