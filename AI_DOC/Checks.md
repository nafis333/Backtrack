# CHECKS — verification checklist per phase. Current section loaded on demand.
# [ ]=not verified [V]=code trace verified [x]=manually verified [!]=failed [N/A]=removed

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 1-4 — COMPLETE (all verified)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
See previous checklist.md for full Phase 1-4 verification records.
Key: 135/135 tests passing. All EC cases verified. All UNTP drawer checks verified.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 5 — COMPLETE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── Module 2 Hit Rate ───────────────────────────────────────
HR1  [V] original_tp: hit_tp = win
HR2  [V] original_tp: hit_sl/hit_be = loss
HR3  [V] fixed_tp: mfe_r >= rr_target = win
HR4  [V] pips unit: tp_value / sl_distance_pips
HR5  [V] fixed_untp: mfe_at_Xh_r >= target = win
HR6  [V] fixed_untp: alive_col never read — alive irrelevant (R11)
HR7  [V] fixed_untp: mfe_val is None → inconclusive
HR8  [V] untp_overview: returns open/sl/be; win_rate=None
HR9  [V] one row per distinct symbol
HR10 [V] one row per distinct trade_type
HR11 [V] session labels: all 5 sessions covered
HR12 [V] DOW: if dow_num in _DOW_LABELS guard — weekend/None excluded
HR13 [V] row dict has wins/losses/inconclusive/win_rate/net_rr
HR14 [V] sorted count desc; dow uses Mon-Fri fixed order
HR15 [V] price_path_captured=False excluded per row
HR16 [V] denominator = wins + losses (no alive filter)
HR17 [V] inconclusive excluded from denominator
HR18 [V] win_rate=None when evaluated=0; JS shows dash
HR19 [V] same payload sent to both /overview and /hitrate

── Module 7 PnL Report ─────────────────────────────────────
PR1  [V] equity curve = cumulative pnl_r, entry_time ASC
PR2  [V] open/none (pnl_r=NULL) excluded
PR3  [V] hit_be (pnl_r=0.0) = flat step
PR4  [V] price_path_captured=False excluded
PR5  [V] weekly totals = sum pnl_r per ISO week
PR6  [V] monthly totals = sum pnl_r per month
PR7  [V] weekly totals sum to monthly (no double-counting)
PR8  [V] zero-trade weeks shown as 0.0 not omitted
PR9  [V] period boundaries use entry_time not saved_at
PR10 [V] per-symbol net RR = sum pnl_r for symbol
PR11 [V] sum per-symbol = overall net RR
PR12 [V] symbols sorted net RR descending
PR13 [V] zero-count symbols excluded
PR14 [V] win streak = consecutive hit_tp entry_time order
PR15 [V] loss streak = consecutive hit_sl
PR16 [V] hit_be = skip (not counted, not streak-breaking)
PR17 [V] open/none = skip
PR18 [V] streak rules match R5/R6
PR19 [V] zero trades: no crash, all totals 0.0
PR20 [V] single trade: equity 1 point, streak 1 or 0
PR21 [V] all hit_be: net RR=0.0, streaks=0
PR22 [V] date range: only trades in range appear

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PHASE 6 — NOT STARTED
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

── Walk Engine ─────────────────────────────────────────────
[ ] WE1  data_frames pre-loaded — zero disk reads per request
[ ] WE2  stop_reason 'sl': original SL price breached
[ ] WE3  stop_reason 'be': price hit be_trigger_r then retraced to entry
[ ] WE4  stop_reason 'time_limit': max_minutes reached before natural stop
[ ] WE5  stop_reason 'open': parquet data exhausted
[ ] WE6  WalkDataError raised when entry candle not in parquet
[ ] WE7  30240 min (504h) cap enforced always
[ ] WE8  be_active=False: stop_reason never 'be'
[ ] WE9  be_active=True: BE triggers at user be_trigger_r, not saved trade config
[ ] WE10 path output: [[elapsed_min, mfe_r, mae_r], ...] every candle
[ ] WE11 No DB writes (R2)
[ ] WE12 Performance warning >100 trades, confirm >300

── M1 fixed_untp Upgrade ───────────────────────────────────
[ ] FU1  Route calls walk_trade_untp() — not mfe_at_Xh_r stored column
[ ] FU2  Returns stats_be_on + stats_be_off
[ ] FU3  BE on walk uses user-supplied be_trigger_r
[ ] FU4  Win = peak_mfe_r >= target; alive irrelevant (R11)
[ ] FU5  No-limit maps to max_minutes=30240
[ ] FU6  Open trades included — peak_mfe from available data
[ ] FU7  WalkDataError trades excluded, count in excluded_count

── M1 untp_overview Upgrade ────────────────────────────────
[ ] UO1  Route calls walk_trade_untp() — not alive_at_Xh stored column
[ ] UO2  Returns stats_be_on + stats_be_off
[ ] UO3  Open = stop_reason in (time_limit, open)
[ ] UO4  SL = stop_reason == 'sl'
[ ] UO5  BE = stop_reason == 'be' (be_on walk only; never in be_off walk)
[ ] UO6  Old sidebar BE toggle removed from statistics.html

── M1 UI Changes ───────────────────────────────────────────
[ ] UI1  BE On / BE Off / Difference buttons in results area
[ ] UI2  BE On renders stats_be_on
[ ] UI3  BE Off renders stats_be_off
[ ] UI4  Difference opens drawer-style comparison page
[ ] UI5  Time limit dropdown includes No limit at top
[ ] UI6  be_trigger_r input visible when BE On selected
[ ] UI7  Switching BE On/Off re-renders from cached response — no re-fetch

── M3 RR Sweep ─────────────────────────────────────────────
[ ] SW1  Server returns path per trade (one BE mode per request)
[ ] SW2  Client holds path permanently — no re-fetch on slider move
[ ] SW3  peak_mfe = max(mfe_r) where elapsed_min <= limit
[ ] SW4  Unalive trades counted if path reached target before stopping
[ ] SW5  Win = peak_mfe >= target; denominator = all trades
[ ] SW6  Adaptive steps: 0.25 up to 3R, 0.5 up to 6R, 1.0 beyond
[ ] SW7  EV = (wr × target) + (lr × -1.0)
[ ] SW8  Avg MAE before target: wins only, max mae up to first target hit
[ ] SW9  MAE:Target ratio = avg_mae_before / target
[ ] SW10 Median time-to-target: wins only
[ ] SW11 Max consec losses: entry_time order, R6 rule
[ ] SW12 Early exit %: wins where 75% of target hit in first 25% of limit
[ ] SW13 Confidence: Red<20 / Yellow 20-49 / Green 50+
[ ] SW14 Best EV row marked ★
[ ] SW15 Best risk-adjusted = EV/(max_consec_losses+1) marked ◆
[ ] SW16 Dead zone EV<0 greyed
[ ] SW17 Time limit slider instant client-side
[ ] SW18 Session filter instant client-side
[ ] SW19 BE switching triggers new server request, cached per mode
[ ] SW20 Difference drawer shows per-target changes between BE modes

── M4 BE Comparison ────────────────────────────────────────
[ ] BE1  All price_path_captured=True trades included
[ ] BE2  Group A: fresh re-walk with be_active=True, user be_trigger_r
[ ] BE3  Group B: fresh re-walk with be_active=False, SL only
[ ] BE4  be_trigger_r always required for this module
[ ] BE5  BE count always 0 in Group B
[ ] BE6  Difference column shows Group B - Group A
[ ] BE7  BE On / BE Off / Difference drawer pages
[ ] BE8  Empty state handled gracefully

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OPEN MANUAL CHECKS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[ ] ST19 Selecting Limit Buy in statistics filters to limit_buy trades only — manual verify needed
[ ] SR1-SR28 Phase 4 statistics redesign mode checks — manual verify needed with real data