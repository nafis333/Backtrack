# NAV — topic to file to function. Pure lookup. Append-only.

## Modify / Build
save-time trade walk logic           utils/mfe_calculator.py          calculate_mfe() candle loop
save-time UNTP walk logic            utils/mfe_calculator.py          calculate_mfe() candle loop
candle iteration order               utils/mfe_calculator.py          sections a-g inside loop
post-walk cleanup dip/BE phantom     utils/mfe_calculator.py          after loop before result dict
streak calculation                   utils/mfe_calculator.py          _compute_streak()
pnl_r assignment                     utils/mfe_calculator.py          Section 9 Derive outcome
query-time re-walk (Phase 6+)        utils/walk_engine.py             walk_trade_untp()
pip sizes                            utils/pip_utils.py               get_pip_size()
win/loss classification orig/fixed   utils/trade_statistics.py        resolve_win_loss()
fixed_untp classification            utils/trade_statistics.py        compute_fixed_untp_overview()
untp_overview bucketing              utils/trade_statistics.py        compute_untp_stats()
Module 2 hit rate computation        utils/trade_statistics.py        compute_hit_rate()
Module 7 PnL report computation      utils/trade_statistics.py        compute_pnl_report()
statistics filter and load           routes/statistics_routes.py      _load_trades()
statistics dispatch by mode          routes/statistics_routes.py      statistics_overview()
M3 RR Sweep route (Phase 6)         routes/statistics_routes.py      statistics_sweep()
M4 BE Compare route (Phase 6)       routes/statistics_routes.py      statistics_becompare()
save flow orchestration              routes/save_routes.py            save_trade()
channel CRUD                         utils/trade_storage.py           create/delete/archive_channel()
channel metadata                     utils/trade_storage.py           get_all_channel_metas()
channel detail context               utils/trade_storage.py           get_channel_detail_context()
CSV export columns                   utils/trade_storage.py           _CSV_COLUMNS
DB schema                            db.py                            Trade model
trade serialisation                  db.py                            Trade.to_dict()
monitor form processing              app.py                           monitor_trade_route()
TP drawer JS                         templates/channel_detail.html    renderDrawerContent()
UNTP drawer JS                       templates/channel_detail.html    openUntpDrawer()
RR/Pips toggle                       templates/channel_detail.html    show-pips on body (CSS-driven)
Module 1 UI                          templates/partials/stats_m1_overview.html   renderOverview() renderUntpStats()
Module 2 UI                          templates/partials/stats_m2_hitrate.html    renderHitRate()
Module 3 UI (Phase 6)               templates/partials/stats_m3_sweep.html      —
Module 4 UI (Phase 6)               templates/partials/stats_m4_becompare.html  —
Module 7 UI                          templates/partials/stats_m7_pnl.html        renderPnlReport()
parquet data loading                 data_loader.py                   data_frames dict
NAS100 filename mapping              utils/trade_calculations.py      FILE_NAME_MAPPING get_file_name()
input validation monitor             utils/trade_validation.py        process_trade_inputs()
input validation save                routes/save_routes.py            _parse_form()

## Debug
wrong win rate                       utils/trade_statistics.py        resolve_win_loss()
wrong fixed_untp result              utils/trade_statistics.py        compute_fixed_untp_overview()
wrong UNTP classification Phase 6+   utils/walk_engine.py             walk_trade_untp()
streak wrong                         utils/mfe_calculator.py          _compute_streak()
save fails                           routes/save_routes.py            _parse_form() → save_trade()
statistics page crash                routes/statistics_routes.py      statistics_hub() + JS console
drawer JS crash                      templates/channel_detail.html    const TDZ in renderDrawerContent
pnl_r wrong                          utils/mfe_calculator.py          Section 9 — R1 never derive
mfe_path wrong sampling              utils/mfe_calculator.py          last_path_min += 15 (R15)
parquet data missing                 data_loader.py                   data_frames dict key check
symbol not found in walk             utils/walk_engine.py             WalkDataError handling
CSV missing columns                  utils/trade_storage.py           _CSV_COLUMNS list

## Add New
statistics module                    new partial file only. One tab str_replace in statistics.html.
source file                          create file + append AI/STUBS.md + AI/NAV.md + AI/STATE.md
DB column                            db.py + delete trades.db + migration + to_dict() + save_routes + mfe_calculator _empty_result()
parquet symbol                       utils/symbols.py + Stored files/ + pip_utils if new pip size