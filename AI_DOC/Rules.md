# RULES — permanent constraints. Never break these. Append-only.

## Absolute Rules
R1   pnl_r is the ONLY P&L field. Never derive from MFE or outcome strings.
     hit_tp=+tp_rr_target | hit_sl=-1.0 | hit_be=0.0 | open/none=NULL
R2   Statistics are dynamic, never stored. win_rate/EV/net_rr never written to DB.
R3   price_path_captured=False → exclude from ALL statistics always.
R4   db.create_all() never adds columns. Schema change = delete trades.db + migration.
R5   trade_monitor.py READ-ONLY. Never modify.
R6   Streak: hit_tp=+1, hit_sl=-1, hit_be/open/none=SKIP. ORDER BY entry_time DESC.
R7   hit_be context split:
       Statistics win-rate original_tp mode: hit_be = LOSS
       Streak context: hit_be = SKIP
R8   Always use pip_utils.get_pip_size(). Never hardcode pip sizes.
     XAUUSD=0.1 | XAGUSD=0.01 | NAS100/US30=1.0 | USOIL/UKOIL=0.1 | JPY=0.01 | others=0.0001
     NAS100 maps to USTEC in parquet filenames.
R9   Post-walk cleanup fires AFTER loop, never inside.
     Dip: peak_dip_time >= resolution_candle_time → zero all dip fields
     BE:  outcome=hit_tp AND be_trigger_min==resolution_min → clear all BE fields
R10  walk_engine BE logic uses user-supplied be_trigger_r only.
     Never read trade.breakeven_active / trade.breakeven_value / trade.breakeven_type.
     Both BE walks (on/off) are fresh re-walks regardless of saved trade state.
R11  fixed_untp win = peak_mfe_r >= target. alive_at_Xh is IRRELEVANT. (BUG-16, DECISION-22)
R12  statistics.html shell FROZEN (DECISION-18). New module = new partial only.
R13  UNTP notes → Trade.untp_notes. TP notes → Trade.notes. Never cross-write.
R14  JS const TDZ in renderDrawerContent — scan full function before adding any const.
R15  mfe_path sampling: last_path_min += 15. Never = elapsed_min. (BUG-3)
R16  Open trades in walk_engine: walk to parquet end, capped at 30240 min (504h).
     Entry candle not in parquet = WalkDataError = trade excluded.

## Candle Iteration Order (save-time — never reorder)
a.elapsed_time  b.R_milestones  c.dip_check  d.BE_trigger  e.SL_check  f.TP_check  g.UNTP_snapshot

## UNTP Bucket Rules — channel detail only (DECISION-12)
Running = alive=true at window (any MFE sign)
SL      = alive=false AND be_triggered=false → -1.0R
BE      = alive=false AND be_triggered=true  →  0.0R

## walk_engine stop_reason values
'sl'         → original SL hit → SL bucket
'be'         → BE triggered at be_trigger_r then entry retraced → BE bucket (be_active=True only)
'time_limit' → max_minutes reached → Open bucket
'open'       → parquet exhausted → Open bucket

## JS Declaration Order (renderDrawerContent — strict TDZ)
DAYS/streakVal/_outcome → _streakIsNeutral/streakDisplay → ref/_refMfe/_refMae/_refStopped
→ _dip/_advCandles → shapeName → metrics → refLabel → innerHTML

## Key Field Distinctions
t.mae_r         — trade walk frozen at close. MFE:MAE denominator for hit_tp.
mae_at_Xh_r     — UNTP walk only. NOT for MFE:MAE ratio.
mfe_after_be_r  — trade walk: BE activation to TRADE CLOSE (not UNTP stop).
mfe_path_json   — [[elapsed_min, mfe_r, mae_r, untp_alive], ...] 15-min sampled. Display only Phase 6+.
alive_at_Xh     — UNTP walk status only. NOT trade status.
outcome_at_Xh   — TRADE outcome only. NOT UNTP walk.
MAE Pressure    — t.mae_r ONLY. Not UNTP MAE.