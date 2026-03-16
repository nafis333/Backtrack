# STATE — current version and status per source file. Append-only. Last entry per file = truth.
# FORMAT: [date] FILE: vN | STATUS | key changes

[2026-03-15] utils/mfe_calculator.py: v7 | STABLE | save-time walk engine. Do not touch walk order or post-walk cleanup.
[2026-03-15] utils/walk_engine.py: NOT CREATED | Phase 6 first task
[2026-03-15] utils/trade_statistics.py: v5 | STABLE | compute_hit_rate + compute_pnl_report + compute_fixed_untp_overview added. BUG-16 fixed. Phase 6 pending: fixed_untp+untp_overview route to walk_engine results.
[2026-03-15] utils/trade_storage.py: v3 | STABLE | P2-GAP-1 fixed (_CSV_COLUMNS all 56 UNTP cols). P2-GAP-2 fixed (move_trade streak recalc both channels).
[2026-03-15] routes/statistics_routes.py: v4 | STABLE | hitrate + pnl routes added. BUG-15 fixed. Phase 6 pending: sweep + becompare routes + walk_engine dispatch.
[2026-03-15] routes/save_routes.py: v2 | STABLE
[2026-03-15] routes/channel_routes.py: v3 | STABLE | untp-notes endpoint added.
[2026-03-15] db.py: v3 | STABLE | untp_notes column added 2026-03-13. Migration done 2026-03-14.
[2026-03-15] app.py: v2 | STABLE
[2026-03-15] data_loader.py: v1 | STABLE
[2026-03-15] utils/pip_utils.py: v1 | STABLE
[2026-03-15] utils/trade_validation.py: v1 | STABLE
[2026-03-15] utils/trade_calculations.py: v1 | STABLE
[2026-03-15] templates/statistics.html: v6 | STABLE — SHELL FROZEN (DECISION-18). Tab M3+M4 buttons need rename to RR Sweep / BE Compare.
[2026-03-15] templates/partials/stats_m1_overview.html: v2 | STABLE | Phase 6 pending: BE On/Off/Difference buttons, be_trigger_r input, No-limit dropdown.
[2026-03-15] templates/partials/stats_m2_hitrate.html: v1 | STABLE — Phase 5 complete
[2026-03-15] templates/partials/stats_m3_sweep.html: PLACEHOLDER — rename from stats_m3_tpsim.html. Phase 6.
[2026-03-15] templates/partials/stats_m4_becompare.html: PLACEHOLDER — rename from stats_m4_sweep.html. Phase 6.
[2026-03-15] templates/partials/stats_m5_dip.html: PLACEHOLDER — Phase 7
[2026-03-15] templates/partials/stats_m6_strategy.html: PLACEHOLDER — Phase 7
[2026-03-15] templates/partials/stats_m7_pnl.html: v1 | STABLE — Phase 5 complete
[2026-03-17] utils/walk_engine.py: v1 | STABLE | walk_trade_untp() + WalkDataError. All WE checks pass static trace.
[2026-03-17] utils/trade_statistics.py: v6 | STABLE | 4 walk-based functions added: _compute_fixed_untp_group_from_walks, compute_fixed_untp_from_walks, _compute_untp_group_from_walks, compute_untp_stats_from_walks
[2026-03-17] routes/statistics_routes.py: v5 | STABLE | Phase 6 dispatch: fixed_untp/untp_overview route to walk_engine. be_trigger_r added to payload. No-limit allowed. data_frames + walk_engine imported.
