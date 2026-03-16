# DEBUG — symptom to cause to file to function. Append-only on new symptom pattern.

## FORMAT: SYMPTOM → likely cause → file → function → what to check

─── Statistics Wrong Results ───────────────────────────────
Wrong win rate (any mode)
  → resolve_win_loss() dispatch error
  → utils/trade_statistics.py → resolve_win_loss()
  → check tp_mode routing, alive gate (R11: alive irrelevant for fixed_untp)

fixed_untp shows same result as untp_overview (ignoring target)
  → BUG-16 pattern: fixed_untp routed to compute_untp_stats() instead of compute_fixed_untp_overview()
  → routes/statistics_routes.py → statistics_overview() dispatch block

fixed_untp win rate wrong despite correct route
  → check alive gate: win must NOT require alive=True (R11)
  → utils/trade_statistics.py → compute_fixed_untp_overview() → win condition

untp_overview buckets wrong
  → Phase 4/5: check alive_at_Xh + breakeven_triggered fields
  → Phase 6+: check walk_engine stop_reason mapping
  → utils/trade_statistics.py → _compute_untp_group() or compute_untp_stats()

walk_engine wrong stop_reason
  → check BE trigger condition: must use be_trigger_r not trade.breakeven_value (R10)
  → check open trade cap: 30240 min max
  → utils/walk_engine.py → walk_trade_untp()

Hit rate DOW showing weekend trades
  → missing if dow_num in _DOW_LABELS guard (HR12)
  → utils/trade_statistics.py → compute_hit_rate() → by_dow population loop

PnL report equity curve wrong
  → check pnl_r is used directly (R1 — never derive from MFE)
  → check ORDER BY entry_time ASC via _load_trades()
  → utils/trade_statistics.py → compute_pnl_report()

─── Save / Walk Wrong Results ──────────────────────────────
pnl_r wrong value
  → ONLY set in mfe_calculator Section 9. Check nowhere else sets it (R1).
  → utils/mfe_calculator.py → Section 9 Derive outcome/pnl_r

Streak wrong after save
  → check ORDER BY entry_time DESC not saved_at (R6)
  → check hit_be = skip not loss
  → utils/mfe_calculator.py → _compute_streak()

mfe_path_json wrong sampling intervals
  → check last_path_min += 15 not = elapsed_min (R15, BUG-3)
  → utils/mfe_calculator.py → path sampling block

UNTP walk stops too early
  → check be_triggered ACTUAL value not breakeven_active config
  → if BE configured but TP fired first: be_triggered=False, stop=original SL
  → utils/mfe_calculator.py → UNTP stop condition

Post-walk dip or BE phantom fields set incorrectly
  → check cleanup runs AFTER loop not inside (R9)
  → utils/mfe_calculator.py → post-walk cleanup section

Save fails with ValueError
  → _parse_form() validation failed — check form field names
  → routes/save_routes.py → _parse_form()

price_path_captured=False saved
  → entry candle not in parquet, or SL distance = 0, or symbol not in data_frames
  → utils/mfe_calculator.py → calculate_mfe() early exit paths

─── UI / JS Crashes ────────────────────────────────────────
Drawer crashes on open (ReferenceError)
  → const TDZ in renderDrawerContent — forward reference (R14)
  → templates/channel_detail.html → renderDrawerContent()
  → scan entire function for existing const uses before adding new one

RR/Pips toggle not working
  → must be CSS-driven via show-pips on body — never JS re-render
  → templates/channel_detail.html → setUnit()

UNTP drawer opens TP drawer content
  → #untpDrawer and #tradeDrawer must be separate elements
  → templates/channel_detail.html → HTML structure

Statistics page crash on load
  → check JS console for import error or route 500
  → routes/statistics_routes.py → statistics_hub()
  → check all imports in trade_statistics.py are valid

─── Data / Schema ──────────────────────────────────────────
Missing DB column after schema change
  → db.create_all() never adds columns (R4)
  → must delete trades.db and run migration

CSV export missing columns
  → _CSV_COLUMNS list missing entries
  → utils/trade_storage.py → _CSV_COLUMNS

Symbol not found in walk
  → data_frames key is uppercase symbol string
  → data_loader.py → data_frames dict
  → NAS100 key is "NAS100" not "USTEC" (filename differs from key)

Notes saved to wrong column
  → TP drawer: POST /trades/<id>/notes → Trade.notes
  → UNTP drawer: POST /trades/<id>/untp-notes → Trade.untp_notes (R13)
  → routes/channel_routes.py → update_trade_notes() vs update_untp_notes()