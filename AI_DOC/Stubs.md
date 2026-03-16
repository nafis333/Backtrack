# STUBS — function signatures and key constraints. Append-only when new functions added.

## utils/walk_engine.py  [Phase 6 — NOT YET CREATED]
walk_trade_untp(trade, data_frames, max_minutes, be_active, be_trigger_r) -> dict
  Returns: peak_mfe_r, peak_mae_r, stop_reason(sl/be/time_limit/open), stopped_at_min, path[[min,mfe,mae],...]
  be_active=True: trigger BE at be_trigger_r. Trade's saved BE config NEVER read. (R10)
  be_active=False: walk to original SL only. stop_reason never 'be'.
  WalkDataError if entry candle not in parquet. Open trades walk to data end, capped at 30240 min. (R16)
  Uses data_frames (pre-loaded). Zero disk I/O. No DB writes.

## utils/trade_statistics.py
resolve_win_loss(trade, tp_mode, tp_value, time_limit_hours, unit) -> 'win'|'loss'|'inconclusive'
  original_tp/fixed_tp only. hit_be=loss in original_tp (R7). alive irrelevant in fixed_tp.

compute_overview(trades, tp_mode, tp_value, time_limit_hours, unit) -> dict
  original_tp and fixed_tp only. result_type='overview'.

compute_fixed_untp_overview(trades, tp_value, time_limit_hours, unit) -> dict
  Win = peak_mfe_r >= target (alive irrelevant — R11). result_type='overview'.
  Phase 4/5: uses stored mfe_at_Xh_r. Phase 6+: uses walk_engine peak_mfe_r.

compute_untp_stats(trades, time_limit_hours, tp_mode, tp_value, unit) -> dict
  untp_overview mode. Phase 6+: returns stats_be_on + stats_be_off from walk_engine results.
  Open = stop_reason in (time_limit, open). SL = sl. BE = be (BE-on walk only).

compute_hit_rate(trades, tp_mode, tp_value, time_limit_hours, unit) -> dict
  result_type='hitrate'. dimensions: symbol/trade_type/session/day_of_week.
  DOW guard: if dow_num in _DOW_LABELS — weekend/None excluded (HR12).

compute_pnl_report(trades) -> dict
  result_type='pnl_report'. Uses pnl_r directly. Mode-agnostic. (R1)

_classify_for_hitrate(trade, tp_mode, tp_value, unit, mfe_col, alive_col) -> (bucket, pnl)
_build_hitrate_rows(groups, tp_mode, tp_value, unit, mfe_col, alive_col, sort_order) -> list
_get_snapshot_cols(time_limit_hours) -> (mfe_col, alive_col)
_get_mae_col(time_limit_hours) -> mae_col
_rr_target_for_trade(trade, tp_value, unit) -> float|None
_effective_pnl(trade, tp_mode, tp_value, result, unit) -> float
_entry_label(trade) -> str
_compute_untp_group(subset, mfe_col, alive_col, mae_col) -> dict

## utils/mfe_calculator.py  [save-time only — do not use for query-time]
calculate_mfe(...) -> dict  [~140 keys matching Trade columns]
  Called by save_routes only. Returns _empty_result() with price_path_captured=False on exception.
_compute_streak(channel_id) -> int
  hit_tp=+1, hit_sl=-1, hit_be/open/none=skip. ORDER BY entry_time DESC. (R6)
_classify_session(hour) -> str  [asian/london/overlap/new_york/off_hours]
_empty_result() -> dict  [all keys=None, price_path_captured=False]

## utils/trade_storage.py
get_all_channel_metas(include_archived) -> list
get_channel_detail_context(channel_id) -> (meta_dict, filter_options_dict)
get_trades_by_channel(channel_id, filters) -> list  [ORDER BY entry_time DESC]
delete_trade(trade_id) -> channel_id  [captured as int before commit — DetachedInstanceError guard]
move_trade(trade_id, new_channel_id)  [calls _recompute_channel_streaks for both channels]
export_trades_csv(channel_id, filters) -> str  [_CSV_COLUMNS: all 56 UNTP cols + mfe_path_json]

## routes/statistics_routes.py
statistics_overview() -> POST /statistics/overview
  Dispatches by tp_mode. Phase 6+: fixed_untp/untp_overview call walk_engine twice per trade.
statistics_hitrate() -> POST /statistics/hitrate  [Module 2]
statistics_pnl() -> POST /statistics/pnl  [Module 7 — ignores tp_mode, uses pnl_r (R1)]
statistics_sweep() -> POST /statistics/sweep  [Phase 6 — M3 RR Sweep]
statistics_becompare() -> POST /statistics/becompare  [Phase 6 — M4 BE Compare]
_load_trades(filters) -> list  [ORDER BY entry_time ASC for equity curve]

## routes/save_routes.py
save_trade() -> POST /save_trade  [parse → channel → calculate_mfe → Trade() → commit]
_parse_form(form) -> dict  [validates, raises ValueError on bad input]
_get_or_create_channel(channel_id, ...) -> Channel

## routes/channel_routes.py
channel_detail(channel_id) -> GET /channels/<id>
update_trade_notes(trade_id) -> POST /trades/<id>/notes  [→ Trade.notes only]
update_untp_notes(trade_id) -> POST /trades/<id>/untp-notes  [→ Trade.untp_notes only — R13]

## db.py
Trade.to_dict() -> dict  [all 140+ fields — only path from DB into statistics engine]
init_db(app)  [called once at startup]

## data_loader.py
data_frames: dict  [module-level. Keys=uppercase symbols. Loaded at startup.]
  Used by: mfe_calculator (save-time) and walk_engine (query-time). Zero disk I/O at query time.

## utils/pip_utils.py
get_pip_size(symbol) -> float  [authoritative. Never hardcode. (R8)]

## utils/trade_calculations.py
get_closing_price(year, month, day, hour, minute, symbol) -> float  [monitor-time only]
get_file_name(symbol) -> str  [NAS100→USTEC mapping]

## utils/trade_statistics.py — Phase 6 additions
_compute_fixed_untp_group_from_walks(pairs, tp_value, unit) -> dict
  pairs=[(trade_dict, walk_result),...]. Win=peak_mfe_r>=target. Returns group stats sub-dict.

compute_fixed_untp_from_walks(pairs_be_on, pairs_be_off, tp_value, unit, total_trades, excluded_count, walk_excluded_count, time_limit_label) -> dict
  result_type='overview_walk'. Returns stats_be_on + stats_be_off.

_compute_untp_group_from_walks(pairs) -> dict
  Buckets by stop_reason: open=(time_limit|open), sl=sl, be=be. Returns group stats sub-dict.

compute_untp_stats_from_walks(pairs_be_on, pairs_be_off, total_trades, excluded_count, walk_excluded_count, time_limit_label) -> dict
  result_type='untp_stats_walk'. Returns stats_be_on + stats_be_off.