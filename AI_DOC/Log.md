# LOG — bugs, decisions, sessions. Append-only. One line per entry. Last 50 lines loaded per session.
# FORMAT: [date] TYPE: content

[2026-03-11] SESSION: Phase 1-3 delivered. Full test suite 135/135. Walk engine hardened. BUG-INT-1 fixed.
[2026-03-11] BUG-1: hit_be counted as loss in streak | fix: hit_be=skip in _compute_streak() | mfe_calculator.py
[2026-03-11] BUG-2: streak ordered by saved_at, corrupted on re-save | fix: ORDER BY entry_time DESC | mfe_calculator.py
[2026-03-11] BUG-3: mfe_path sampling drift = elapsed_min | fix: last_path_min += 15 | mfe_calculator.py
[2026-03-11] BUG-4: wide-candle dip phantom | fix: post-walk cleanup peak_dip_time >= resolution | mfe_calculator.py
[2026-03-11] BUG-5: wide-candle BE phantom | fix: post-walk cleanup outcome=hit_tp AND be_min==resolution | mfe_calculator.py
[2026-03-11] BUG-6: hit_be pnl_r=0.0 returned -1.0 via 'or' | fix: explicit None check | trade_statistics.py
[2026-03-12] SESSION: test_13 30/30 EURUSD. test_14 30/30 statistics. Phase 3 complete. BUG-T13-1 fixed.
[2026-03-13] SESSION: Phase 4 Module 2 DELIVERED. channel_detail.html rewritten. DB migration required.
[2026-03-13] BUG-10: UNTP drawer inside TP drawer | fix: separate #untpDrawer element | channel_detail.html
[2026-03-13] BUG-11: untpPeakMfe only scanned 14 CPs | fix: also iterate mfe_path_json where alive=true | channel_detail.html
[2026-03-13] BUG-12: TP drawer showed Excursion section | fix: removed | channel_detail.html
[2026-03-13] BUG-13: MFE/MAE table columns | fix: removed, all raw MFE/MAE in UNTP drawer only | channel_detail.html
[2026-03-13] DECISION-12: UNTP buckets Running/SL/BE only, no Win | PERMANENT
[2026-03-13] DECISION-13: untp_notes separate column from notes | PERMANENT
[2026-03-14] SESSION: P4-GAP-1 closed. DB migration confirmed. Statistics 4-mode redesign planned.
[2026-03-14] BUG-14: channel cards missing win rate and net R | fix: _build_channel_meta() added | trade_storage.py channels.html
[2026-03-14] DECISION-14: TP drawer always Max mode via resolveUntpRef(). No window selector. | PERMANENT
[2026-03-14] DECISION-15: 4 statistics modes: original_tp/fixed_tp/fixed_untp/untp_overview. fixed_rr/fixed_pips retired. | PERMANENT
[2026-03-14] DECISION-16: RETIRED 2026-03-15 — superseded by DECISION-22
[2026-03-14] DECISION-17: statistics trade direction 7 individual options, no grouping | PERMANENT
[2026-03-15] SESSION: P5-PREREQ-1 delivered. 4-mode statistics implemented. BUG-15/16/17/18 fixed. Phase 5 complete.
[2026-03-15] BUG-15: ImportError compute_untp_overview | fix: corrected import | statistics_routes.py
[2026-03-15] BUG-16: fixed_untp ignored tp_value, routed to untp_stats | fix: compute_fixed_untp_overview() win=mfe_at_Xh_r>=target alive irrelevant | trade_statistics.py
[2026-03-15] BUG-17: _CSV_COLUMNS missing 56 UNTP cols + mfe_path_json | fix: extended _CSV_COLUMNS | trade_storage.py
[2026-03-15] BUG-18: test_14 4 breakage points after BUG-16 fix | fix: import+Groups C/E/L rewritten | test_14_statistics.py
[2026-03-15] DECISION-18: statistics.html shell+partials pattern. Shell frozen. | PERMANENT
[2026-03-15] DECISION-19: claimed_tp_pips/claimed_pnl_r optional fields deferred to Phase 10 | PERMANENT — never required
[2026-03-15] DECISION-20: Module 6 must lead with EV-optimal TP headline from M3 RR Sweep | PERMANENT
[2026-03-15] DECISION-21: TP Simulator dropped. Phase 6=Simulators, 7=Dip+Strategy, 8=Polish. M3=RR Sweep, M4=BE Compare. No first_candle filter. No DOW filter on sweep. | PERMANENT
[2026-03-15] DECISION-22: walk_engine.py is primary data source for fixed_untp+untp_overview Phase 6+. BE=user-supplied be_trigger_r, never saved trade config. DECISION-16 RETIRED. | PERMANENT
[2026-03-15] SESSION: Phase 5 complete. Module 2 Hit Rate + Module 7 PnL delivered 135/135. Major architecture redesign: walk_engine, parquet re-walk, GitHub agent system designed then moved back to project files. All 10 AI agent files + system prompt produced.
[2026-03-17] SESSION: Phase 6 started. walk_engine.py built and verified WE1-WE11. File: utils/walk_engine.py v1.
[2026-03-17] SESSION: Phase 6 continued. statistics_routes.py upgraded — fixed_untp/untp_overview now use parquet re-walk via walk_engine. Four new walk-based compute functions added to trade_statistics.py. M1 frontend update pending.