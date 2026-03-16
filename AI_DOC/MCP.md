{
  "_meta": {
    "file_governance": {
      "system_prompt": "Contains only timeless rules, the two walks, field semantics, and session start protocol. Never contains bug lists, phase status, or session history — those belong in MCP.md.",
      "MCP.md": "Living document. All bugs, decisions, gaps, overrides, phase status, session history. Updated every session by diff/patch only — never full rewrite.",
      "Backtest_Architecture.md": "Absolute. Schema, domain rules, walk semantics, pitfalls. Only changes when architecture changes.",
      "Phases_Backtest.md": "Absolute. Phase specs and what has been built. Only changes when a new phase starts or completes.",
      "checklist.md": "Absolute. Verification items per phase. Only changes when phase status changes.",
      "mcp_update_protocol": "At end of each session, Claude produces ONLY the specific JSON block/section to insert or replace in MCP.md. Never the full file. User pastes it in manually."
    },
    "new_session_checklist": {
      "steps": [
        "1. Read MCP.md (this file) completely",
        "2. Read Backtest_Architecture.md",
        "3. Read the relevant phase section in Phases_Backtest.md",
        "4. Read checklist.md",
        "5. Ask for specific code files needed",
        "6. Before any fix: check bugs_fixed to avoid reintroducing resolved bugs",
        "7. Before any const in renderDrawerContent: check DECLARATION ORDER",
        "8. Any schema change: remind user to delete trades.db"
      ]
    }
  },

  "phase_status": {
    "phase_1": "COMPLETE — all items verified. DB migration DONE (PENDING-1 closed 2026-03-14).",
    "phase_2": "COMPLETE — all items verified. P2-GAP-1 closed 2026-03-15 (BUG-17). P2-GAP-2 closed 2026-03-14.",
    "phase_3": "COMPLETE — 135/135 tests passing. All 16 EC cases verified.",
    "phase_4": "COMPLETE — all items verified. Statistics 4-mode redesign delivered. fixed_untp logic corrected (BUG-16). test_14 fixed (BUG-18).",
    "phase_5": "COMPLETE — Module 2 (Hit Rate) and Module 7 (PnL Report) delivered and verified.",
    "phase_6": "NOT STARTED — Full Simulator Suite: shared parquet re-walk engine (walk_engine.py), M1 fixed_untp + untp_overview upgrade to candle-level re-walk, M3 RR Sweep, M4 BE Comparison. Prerequisite: Phase 5.",
    "phase_7": "NOT STARTED — Module 5 (Dip Analysis) + Module 6 (Strategy Card). Prerequisite: Phase 6.",
    "phase_8": "NOT STARTED — Polish + Bonus Modules. Prerequisite: Phase 7.",
    "phase_10": "NOT STARTED — Claimed TP Tracking (DECISION-19). No prerequisite — add when user ready.",
    "current_focus": "Phase 6: Full Simulator Suite. Build order: walk_engine.py → M1 upgrade → M3 RR Sweep → M4 BE Comparison."
  },

  "known_gaps": {
    "P2-GAP-1": {
      "severity": "CLOSED 2026-03-15",
      "description": "CSV export was missing all 56 UNTP snapshot columns + mfe_path_json. _CSV_COLUMNS in trade_storage.py had only 32 fields. Fixed as BUG-17. NOTE: was incorrectly marked closed 2026-03-14 — columns were not actually present at that time."
    },
    "P2-GAP-2": {
      "severity": "CLOSED 2026-03-14",
      "description": "move_trade() already calls _recompute_channel_streaks() for both source and destination channels. Was fixed at a prior session, never documented as closed. No code change needed."
    },
    "P5-PREREQ-1": {
      "severity": "CLOSED 2026-03-15",
      "description": "Statistics 4-mode redesign delivered: original_tp / fixed_tp / fixed_untp / untp_overview. UNTP panel with Open/SL/BE buckets, BE client-side toggle, equity/drawdown charts."
    },
    "TEST-14-UPDATE": {
      "severity": "CLOSED 2026-03-15",
      "description": "test_14 fully fixed (BUG-18): import updated to compute_untp_stats + compute_fixed_untp_overview. Group C rewritten for new fixed_untp semantics. Group E rewritten. Group L field names corrected. 35/35 passing."
    },
    "STATS-LOGIC-1": {
      "severity": "CLOSED 2026-03-15",
      "description": "fixed_untp was routed to compute_untp_stats() — same as untp_overview — ignoring tp_value entirely. Fixed as BUG-16. compute_fixed_untp_overview() added."
    }
  },

  "critical_rules_learned": [
    {
      "rule": "hit_be = SKIP in streak",
      "location": "mfe_calculator._compute_streak()",
      "constraint": "Never treat hit_be as a loss in streak context."
    },
    {
      "rule": "Streak ORDER BY entry_time DESC",
      "location": "mfe_calculator._compute_streak()",
      "constraint": "Never order by saved_at — re-saves corrupt streak if saved_at is used."
    },
    {
      "rule": "mfe_path uses += 15 not = elapsed_min",
      "location": "mfe_calculator candle loop",
      "constraint": "= elapsed_min causes sampling drift (BUG-3)."
    },
    {
      "rule": "Post-walk cleanup fires AFTER loop",
      "location": "mfe_calculator section 9",
      "constraint": "Dip + BE phantoms on wide-candle TP trades. Must run after loop exits."
    },
    {
      "rule": "MFE:MAE denominator = t.mae_r for hit_tp",
      "location": "channel_detail.html",
      "constraint": "Never use UNTP MAE for MFE:MAE ratio on hit_tp trades."
    },
    {
      "rule": "MAE Pressure = t.mae_r only",
      "location": "channel_detail.html",
      "constraint": "Not UNTP MAE."
    },
    {
      "rule": "JS const order in renderDrawerContent",
      "location": "channel_detail.html",
      "constraint": "TDZ — scan full function before adding any const. Forward references crash at runtime."
    },
    {
      "rule": "db.create_all() never adds columns",
      "location": "Schema changes",
      "constraint": "Must delete trades.db on any schema change."
    },
    {
      "rule": "hit_be = LOSS in statistics win-rate (original_tp mode)",
      "location": "trade_statistics.resolve_win_loss()",
      "constraint": "original_tp mode only — different from streak context (R7)."
    },
    {
      "rule": "alive_at_Xh=False when data exhausted (EC15)",
      "location": "mfe_calculator post-walk fallback",
      "constraint": "If parquet data ends before a checkpoint, alive=False. This is correct, not a bug."
    },
    {
      "rule": "outcome_at_Xh and alive_at_Xh are independent",
      "location": "mfe_calculator snapshots",
      "constraint": "A trade can have outcome_at_4h='hit_tp' AND alive_at_4h=True simultaneously."
    },
    {
      "rule": "UNTP buckets (channel detail): Running/SL/BE only — no Win",
      "location": "channel_detail.html classifyUntpTrade()",
      "constraint": "Running=alive=true (any MFE). SL=alive=false+be_triggered=false→-1R. BE=alive=false+be_triggered=true→0R. PERMANENT — DECISION-12."
    },
    {
      "rule": "UNTP notes stored in untp_notes column, never in notes",
      "location": "db.py, channel_routes.py",
      "constraint": "POST /trades/<id>/untp-notes → untp_notes. POST /trades/<id>/notes → notes. Never mix."
    },
    {
      "rule": "TP drawer always uses resolveUntpRef() Max mode — no user window selector",
      "location": "channel_detail.html",
      "constraint": "Window selector removed in Phase 4 Module 2 rewrite. Do not re-add a selector to the TP drawer."
    },
    {
      "rule": "Statistics modes: fixed_rr and fixed_pips are RETIRED",
      "location": "trade_statistics.py, statistics_routes.py, statistics.html",
      "constraint": "Replaced by fixed_tp and fixed_untp. R/Pips is a shared unit toggle, not separate modes. DECISION-15."
    },
    {
      "rule": "Statistics trade direction: 7 individual options, no grouping",
      "location": "statistics.html radio group, statistics_routes.py _load_trades()",
      "constraint": "All / Buy / Sell / Limit Buy / Limit Sell / Stop Buy / Stop Sell. No grouped buy-side/sell-side. DECISION-17."
    },
    {
      "rule": "fixed_untp win = peak_mfe_r >= target — alive_at_Xh is IRRELEVANT",
      "location": "trade_statistics.compute_fixed_untp_overview() (Phase 4/5) → walk_engine.walk_trade_untp() (Phase 6+)",
      "constraint": "Win = peak_mfe >= target regardless of alive status. Phase 4/5 uses stored mfe_at_Xh_r. Phase 6+ uses candle-level parquet re-walk. Same rule either way. BUG-16, DECISION-22."
    },
    {
      "rule": "Phase 6 parquet re-walk BE logic uses user-defined be_trigger_r — never saved trade BE config",
      "location": "walk_engine.walk_trade_untp()",
      "constraint": "BE active walk: trigger BE when price reaches user-supplied be_trigger_r in favour, then stop at entry retrace. BE inactive walk: walk to original SL only. Trade's breakeven_active / breakeven_value are never read by walk_engine. DECISION-22."
    },
    {
      "rule": "Open trades in re-walk: walk to parquet end capped at 504h; entry not in parquet = WalkDataError",
      "location": "walk_engine.walk_trade_untp()",
      "constraint": "stop_reason='open' = parquet exhausted, peak_mfe used as-is. WalkDataError = entry candle not found = trade excluded from results. DECISION-22."
    },
    {
      "rule": "Statistics module tab numbering — DECISION-21",
      "location": "statistics.html shell, partials/",
      "constraint": "M1=Overview, M2=Hit Rate, M3=RR Sweep (Phase 6), M4=BE Compare (Phase 6), M5=Dip (Phase 7), M6=Strategy (Phase 7), M7=PnL Report. TP Simulator dropped. Old stats_m3_tpsim.html and stats_m4_sweep.html placeholders to be renamed/replaced in Phase 6."
    }
  ],

  "bugs_fixed": [
    {
      "id": "BUG-1",
      "description": "hit_be counted as loss in streak — broke win streaks incorrectly.",
      "fix": "hit_be now = skip in _compute_streak(). Only hit_tp (+1) and hit_sl (-1) affect streak."
    },
    {
      "id": "BUG-2",
      "description": "Streak ordered by saved_at. Re-saving an old trade placed it at position 0, corrupting the streak.",
      "fix": "ORDER BY entry_time DESC in _compute_streak()."
    },
    {
      "id": "BUG-3",
      "description": "mfe_path sampling used last_path_min = elapsed_min causing drift.",
      "fix": "Changed to last_path_min += PATH_INTERVAL_MIN."
    },
    {
      "id": "BUG-4",
      "description": "Wide-candle dip phantom: dip recorded and TP fired on same candle.",
      "fix": "Post-walk cleanup: if peak_dip_time >= resolution_candle_time → zero all dip fields."
    },
    {
      "id": "BUG-5",
      "description": "Wide-candle BE phantom: BE triggered and TP fired on same candle.",
      "fix": "Post-walk cleanup: if outcome='hit_tp' and be_trigger_min == resolution_min → clear all BE fields."
    },
    {
      "id": "BUG-6",
      "description": "_effective_pnl used `pnl_r or -1.0`. hit_be trades (pnl_r=0.0) returned -1.0.",
      "fix": "Explicit None check: `v = trade.get('pnl_r'); return float(v) if v is not None else -1.0`."
    },
    {
      "id": "BUG-10",
      "description": "UNTP drawer rendered inside TP drawer body via mode toggle — wrong architecture.",
      "fix": "Complete rewrite of channel_detail.html. Separate #untpDrawer element. Removed wrong toggle approach.",
      "files": ["channel_detail.html", "db.py", "channel_routes.py"]
    },
    {
      "id": "BUG-11",
      "description": "untpPeakMfe() only scanned 14 checkpoints. Inter-checkpoint peaks in mfe_path_json invisible.",
      "fix": "untpPeakMfe() now also iterates mfe_path_json entries where untp_alive=true."
    },
    {
      "id": "BUG-12",
      "description": "TP drawer showed raw Excursion section (MFE, MAE, MFE at Close, Retracement, Dip).",
      "fix": "Removed EXCURSION section and 4 display variables from renderDrawerContent()."
    },
    {
      "id": "BUG-13",
      "description": "Main table had MFE/MAE columns. TP drawer BE section had MFE at BE / MFE after BE.",
      "fix": "Removed MFE/MAE table columns (TABLE_COLS 15→13). All raw MFE/MAE now in UNTP drawer only."
    },
    {
      "id": "BUG-14",
      "description": "Channel cards showed trade count only — win rate and net R missing.",
      "fix": "_build_channel_meta() now computes net_r, win_rate, evaluated_count. channels.html renders them.",
      "files": ["trade_storage.py", "channels.html"]
    },
    {
      "id": "BUG-15",
      "description": "statistics_routes.py imported compute_untp_overview after trade_statistics.py renamed it to compute_untp_stats. Caused ImportError on app startup.",
      "fix": "statistics_routes.py replaced with corrected import."
    },
    {
      "id": "BUG-16",
      "date": "2026-03-15",
      "description": "fixed_untp routed to compute_untp_stats() — same path as untp_overview — ignoring tp_value entirely. Both modes produced identical 3-bucket output regardless of target.",
      "fix": "compute_fixed_untp_overview() added to trade_statistics.py. Win = mfe_at_Xh_r >= target (UNTP peak, frozen at stop; alive irrelevant). Returns result_type='overview'. Dispatch split in statistics_routes.py. modeLabels updated in statistics.html.",
      "files": ["trade_statistics.py", "statistics_routes.py", "statistics.html"]
    },
    {
      "id": "BUG-17",
      "date": "2026-03-15",
      "description": "P2-GAP-1: _CSV_COLUMNS in trade_storage.py had only 32 fields — all 56 UNTP snapshot columns and mfe_path_json were missing from CSV export. Was incorrectly marked closed 2026-03-14.",
      "fix": "_CSV_COLUMNS extended with all 14 × 4 = 56 UNTP columns + mfe_path_json.",
      "files": ["trade_storage.py"]
    },
    {
      "id": "BUG-18",
      "date": "2026-03-15",
      "description": "test_14_statistics.py had 4 breakage points after BUG-16 fix and DECISION-15 redesign: (1) import of non-existent compute_untp_overview, (2) Group C called resolve_win_loss(tp_mode='fixed_untp') which is no longer valid, (3) Group E called compute_overview(tp_mode='fixed_untp') producing all-inconclusive results, (4) Group L used old function name + old field names.",
      "fix": "Import updated. Group C rewritten to call compute_fixed_untp_overview() with new alive-irrelevant semantics. Group E rewritten. Group L updated to compute_untp_stats() with correct field names (open_count/sl_count/be_count). 35/35 passing.",
      "files": ["test_14_statistics.py"]
    },
    {
      "id": "BUG-INT-1",
      "description": "test_12 had wrong year 2025 in entry_time.",
      "fix": "Changed datetime(2025,...) to datetime(2026,...) in _KNOWN_TRADE."
    },
    {
      "id": "BUG-T13-1",
      "description": "test_T13_22 asserted alive_at_Xh=True for all 14 checkpoints. Parquet covers ~48h only.",
      "fix": "Removed alive_at_Xh assertion. EC15 data exhaustion is correct behaviour."
    }
  ],

  "decisions": [
    {
      "id": "DECISION-12",
      "date": "2026-03-13",
      "context": "UNTP PnL bar bucket definitions (channel detail view)",
      "decision": "UNTP buckets: Running = alive=true at window (any MFE). SL = alive=false AND be_triggered=false → -1.0R. BE = alive=false AND be_triggered=true → 0.0R. No Win concept.",
      "rule": "PERMANENT — UNTP channel detail has no wins. alive=true is always Running regardless of MFE sign."
    },
    {
      "id": "DECISION-13",
      "date": "2026-03-13",
      "context": "untp_notes column",
      "decision": "Added untp_notes TEXT column to Trade model. Stored separately from notes. Endpoint: POST /trades/<id>/untp-notes.",
      "rule": "PERMANENT — UNTP notes always stored in untp_notes, never in notes."
    },
    {
      "id": "DECISION-14",
      "date": "2026-03-14",
      "context": "TP drawer MFE window selector",
      "decision": "DR4/DR7 (15-option window selector in TP drawer) removed in Phase 4 Module 2 rewrite. resolveUntpRef() Max mode is the permanent replacement. Do not re-add a user-facing selector to the TP drawer.",
      "rule": "PERMANENT — TP drawer always uses Max mode via resolveUntpRef()."
    },
    {
      "id": "DECISION-15",
      "date": "2026-03-14",
      "context": "Statistics TP Evaluation mode redesign",
      "decision": "4 modes: original_tp (win=hit_tp, loss=hit_sl/hit_be, time limit disabled), fixed_tp (win=mfe_r>=target using trade walk peak, no UNTP, time limit disabled), fixed_untp (win=peak_mfe>=target, alive irrelevant, time limit or no-limit — Phase 6 upgrades to parquet re-walk), untp_overview (no target, Open/SL/BE distribution, no win rate, time limit or no-limit — Phase 6 upgrades to parquet re-walk). R/Pips is a shared unit pill toggle visible for fixed_tp and fixed_untp only.",
      "rule": "PERMANENT — fixed_rr and fixed_pips mode names retired. fixed_untp win does NOT require alive_at_Xh=True. Phase 6 upgrades both to parquet re-walk."
    },
    {
      "id": "DECISION-16",
      "date": "2026-03-14",
      "context": "BE re-walk simulator timing — RETIRED 2026-03-15",
      "decision": "RETIRED. Originally said no query-time parquet walks before Phase 8. Superseded by DECISION-22. Phase 6 now builds the parquet re-walk engine.",
      "rule": "RETIRED — replaced by DECISION-22. Query-time parquet walks are the core of Phase 6."
    },
    {
      "id": "DECISION-17",
      "date": "2026-03-14",
      "context": "Statistics trade direction filter",
      "decision": "Replaced All/Buy-side/Sell-side (3 options) with All/Buy/Sell/Limit Buy/Limit Sell/Stop Buy/Stop Sell (7 options). No grouped options in statistics. Backend _load_trades() already handles individual types.",
      "rule": "PERMANENT — statistics trade direction uses 7 individual options. No grouped buy-side/sell-side."
    },
    {
      "id": "DECISION-18",
      "date": "2026-03-15",
      "context": "statistics.html file size management",
      "decision": "statistics.html split into shell + 7 partials using Jinja2 {% include %}. Shell contains: nav, sidebar, shared CSS, shared JS. Each module is a self-contained partial. Shell frozen — only changes if sidebar or shared infrastructure changes.",
      "rule": "PERMANENT — every new statistics module is a new partial file only. Never add module HTML or module JS to the shell."
    },
    {
      "id": "DECISION-19",
      "date": "2026-03-15",
      "context": "Claimed TP/PnL tracking for dishonest channel signals",
      "decision": "Optional claimed_tp_pips and claimed_pnl_r fields to be added to Trade model in Phase 10. Never required. When populated, channel detail table shows Claimed vs Actual column. Strategy Card shows the gap.",
      "rule": "PERMANENT — claimed fields are always optional. Never block any feature on their presence."
    },
    {
      "id": "DECISION-20",
      "date": "2026-03-15",
      "context": "EV-maximizing TP headline in Module 6 Strategy Card",
      "decision": "Module 6 must surface: 'Optimal hold: Xh · Best TP: Y R · EV: +Z R per trade'. Peak EV point from M3 RR Sweep.",
      "rule": "PERMANENT — Module 6 Strategy Card must lead with EV-optimal TP headline from M3 RR Sweep."
    },
    {
      "id": "DECISION-21",
      "date": "2026-03-15",
      "context": "Phase restructure, TP Simulator dropped, tab renumbering",
      "decision": "Old Phase 6 (checkpoint sweep) cancelled — too coarse for scalper. TP Simulator dropped — RR sweep with no-time-limit covers the use case. Phases renumbered: Phase 6 = Full Simulator Suite, Phase 7 = Dip + Strategy, Phase 8 = Polish + Bonus. Statistics tabs: M3=RR Sweep, M4=BE Compare, M5=Dip, M6=Strategy. First candle filter dropped from sweep. Day-of-week filter dropped from sweep. stats_m3_tpsim.html placeholder renamed/replaced with stats_m3_sweep.html. stats_m4_sweep.html placeholder replaced with stats_m4_becompare.html.",
      "rule": "PERMANENT — No TP Simulator. No first candle filter. No day-of-week filter on sweep. Tab order M1/M2/M3/M4/M5/M6/M7."
    },
    {
      "id": "DECISION-22",
      "date": "2026-03-15",
      "context": "Parquet re-walk as primary data source for UNTP statistics (Phase 6+)",
      "decision": "Phase 6 builds walk_engine.walk_trade_untp() using already-loaded data_frames dict (zero disk I/O). This replaces stored mfe_at_Xh_r / alive_at_Xh as the data source for M1 fixed_untp and M1 untp_overview. Stored columns kept for channel detail drawer and mfe_path_json path chart only. Walk engine rules: (1) BE active walk — trigger BE at user-supplied be_trigger_r, stop at entry retrace. BE inactive walk — walk to original SL only. Trade's breakeven_active/breakeven_value never read. (2) Open trades walk to parquet end, capped at 504h (stop_reason='open'). (3) Entry candle not in parquet = WalkDataError = trade excluded from results. (4) M1 'No limit' option = max_minutes=30240 (504h cap). (5) be_trigger_r is a separate input per module — M1 and M3 each have their own. (6) Results show stats_be_on and stats_be_off side by side. Old sidebar BE toggle (All/BE Active/No BE based on stored breakeven_triggered) removed. New UI: BE On / BE Off / Difference drawer-style buttons in results area.",
      "rule": "PERMANENT — All fixed_untp and untp_overview classification uses parquet re-walk from Phase 6 onwards. BE logic in walk_engine is always user-defined, never read from saved trade data."
    }
  ],

  "test_suite": {
    "layout": {
      "location": "tests/ folder (same level as app.py)",
      "pytest_ini": "tests/pytest.ini — testpaths=tests, pythonpath=.",
      "run_all": "cd 'backtest app' && python3 -m pytest tests/ -q",
      "run_one": "cd 'backtest app' && python3 -m pytest tests/test_13_eurusd_scenarios.py -v"
    },
    "key_decisions": [
      "data_loader mocked in sys.modules at conftest module level before mfe_calculator import",
      "utils.pip_utils NOT mocked — ImportError fires naturally, local fallback runs",
      "clean_data_frames autouse=True — no candle bleed between tests",
      "mock_streak autouse=True — walk tests get streak=0; test_10 captures original at import time",
      "BE trigger floating-point pitfall: be_trigger_price has fp imprecision (~1e-13). Candle highs/lows must be strictly past the level to guarantee trigger fires.",
      "Integration tests skip automatically if parquet file absent — safe for CI",
      "test_13 checks both 'Stored files/' and 'utils/Stored files/' for EURUSD.parquet",
      "T13_22 alive_at_Xh NOT asserted — parquet window ~48h; checkpoints >48h correctly alive=False (EC15)"
    ],
    "totals": {
      "unit_tests": "70 (tests 01–11, 14 — synthetic DataFrames)",
      "total": "135/135 passing"
    },
    "chunks": {
      "chunk_0": "DELIVERED 2026-03-11 — pytest.ini + conftest.py + helpers.py",
      "chunk_1": "DELIVERED 2026-03-11 — test_01_basic_buy.py — 5/5",
      "chunk_2": "DELIVERED 2026-03-11 — test_02_sell.py — 5/5",
      "chunk_3": "DELIVERED 2026-03-11 — test_03_breakeven.py — 6/6",
      "chunk_4": "DELIVERED 2026-03-11 — test_04_wide_candle.py — 4/4",
      "chunk_5": "DELIVERED 2026-03-11 — test_05_untp.py — 6/6",
      "chunk_6": "DELIVERED 2026-03-11 — test_06_limit_orders.py — 6/6",
      "chunk_7": "DELIVERED 2026-03-11 — test_07_stop_orders.py — 7/7",
      "chunk_8": "DELIVERED 2026-03-11 — test_08_pip_sizes.py — 7/7",
      "chunk_9": "DELIVERED 2026-03-11 — test_09_sampling.py — 6/6",
      "chunk_10": "DELIVERED 2026-03-11 — test_10_streak.py — 7/7",
      "chunk_11": "DELIVERED 2026-03-11 — test_11_edge_cases.py — 6/6",
      "chunk_12": "DELIVERED 2026-03-11 — test_12_integration.py — 5/5 on real NZDUSD parquet.",
      "chunk_13": "DELIVERED 2026-03-12 — test_13_eurusd_scenarios.py — 30/30 on real EURUSD Feb 24-25 2026.",
      "chunk_14": "UPDATED 2026-03-15 — test_14_statistics.py — 35/35. BUG-18: import fixed (compute_untp_stats + compute_fixed_untp_overview). Group C rewritten for new fixed_untp semantics (alive irrelevant). Group E rewritten. Group L field names corrected (open_count/sl_count/be_count)."
    },
    "uncovered_fields": [
      "retracement_from_mfe_r — computed correctly, not displayed (N/A), no assertion needed",
      "time_to_mfe_minutes / time_to_mae_minutes — computed correctly, no dedicated assertion",
      "first_candle_direction / consecutive_adverse_candles — computed correctly, no dedicated assertion",
      "avg_candle_size_pips_at_entry — computed correctly, no dedicated assertion",
      "pending_wait_minutes — presence tested, value not asserted quantitatively",
      "mfe_after_be_r — presence/null tested, value correctness not asserted"
    ],
    "future_integration_fixtures": "Add known hit_sl, hit_be, XAUUSD trades to test_12."
  },

  "session_log": [
    {
      "date": "2026-03-11",
      "summary": "Full test suite delivered (chunks 0-12). 70/70 passing. BUG-INT-1 fixed in test_12."
    },
    {
      "date": "2026-03-12",
      "summary": "test_13 (30/30 EURUSD) and test_14 (30/30 statistics) delivered. Total 130/130. Phase 3 complete. BUG-T13-1 fixed. Full mfe_calculator audit: no bugs found."
    },
    {
      "date": "2026-03-13",
      "summary": "Phase 4 Module 2 DELIVERED. channel_detail.html rewritten (BUG-10). BUG-11/12/13 fixed. DECISION-12/13 permanent. DB migration required (PENDING-1).",
      "files_changed": ["channel_detail.html", "db.py", "channel_routes.py"]
    },
    {
      "date": "2026-03-14",
      "summary": "P4-GAP-1 closed. PENDING-1 closed. P2-GAP-2 confirmed already fixed. Statistics 4-mode redesign planned (DECISION-15). DECISION-16 (now RETIRED by DECISION-22). DECISION-17.",
      "files_changed": ["statistics.html", "MCP.md", "Phases_Backtest.md", "checklist.md"]
    },
    {
      "date": "2026-03-15",
      "summary": "P5-PREREQ-1 DELIVERED. Statistics 4-mode redesign implemented. BUG-15 fixed.",
      "files_changed": ["trade_statistics.py", "statistics_routes.py", "statistics.html"]
    },
    {
      "date": "2026-03-15",
      "summary": "index.html redesigned. Nav bar added. datetime-local picker replaces 5 separate inputs.",
      "files_changed": ["index.html"]
    },
    {
      "date": "2026-03-15",
      "summary": "results.html redesigned. Structured outcome card + event timeline. All 6 outcome cases. trade_monitor.py not touched (R10).",
      "files_changed": ["results.html"]
    },
    {
      "date": "2026-03-15",
      "summary": "BUG-16/17/18 fixed. Phase 5 unblocked. STATS-LOGIC-1 + TEST-14-UPDATE + P2-GAP-1 all closed.",
      "files_changed": ["trade_statistics.py", "statistics_routes.py", "statistics.html", "trade_storage.py", "test_14_statistics.py"]
    },
    {
      "date": "2026-03-15",
      "summary": "statistics.html refactored into shell + 7 partials (DECISION-18). Shell frozen.",
      "files_changed": ["statistics.html", "templates/partials/ (7 new files)"]
    },
    {
      "date": "2026-03-15",
      "summary": "Phase 5 Module 2 DELIVERED. compute_hit_rate() + /statistics/hitrate. stats_m2_hitrate.html built. 19/19 HR checks verified.",
      "files_changed": ["trade_statistics.py", "statistics_routes.py", "statistics.html", "templates/partials/stats_m2_hitrate.html"]
    },
    {
      "date": "2026-03-15",
      "summary": "Phase 5 Module 7 DELIVERED. compute_pnl_report() + /statistics/pnl. stats_m7_pnl.html built. 22/22 PR checks verified.",
      "files_changed": ["trade_statistics.py", "statistics_routes.py", "statistics.html", "templates/partials/stats_m7_pnl.html"]
    },
    {
      "date": "2026-03-15",
      "summary": "Phase 5 COMPLETE. System purpose clarified: finding profitable TP for channels that lie about their own. DECISION-19 (claimed TP optional). DECISION-20 (EV headline in Strategy Card). Dropped: limit entry optimizer, signal delay cost, worst-case entry model.",
      "files_changed": ["Phases_Backtest.md", "checklist.md", "MCP.md"]
    },
    {
      "date": "2026-03-15",
      "summary": "Major architecture redesign. DECISION-21: TP Simulator dropped, old checkpoint sweep cancelled, phases renumbered (Phase 6=Simulators, Phase 7=Dip+Strategy, Phase 8=Polish). DECISION-22: parquet re-walk (walk_engine.py) is primary data source for fixed_untp and untp_overview from Phase 6. DECISION-16 RETIRED. BE on/off walk uses user-defined be_trigger_r per module — never reads saved trade BE config. UI pattern: drawer-style BE On/Off/Difference buttons. Old sidebar BE toggle removed. Tab numbering: M3=RR Sweep, M4=BE Compare. All 4 AI docs updated to reflect new architecture.",
      "files_changed": ["MCP.md", "Phases_Backtest.md", "checklist.md", "Backtest_Architecture.md"]
    }
  ]
}