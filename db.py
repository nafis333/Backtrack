from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

def init_db(app):
    import os
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trades.db")
    app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_path}"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()


class Channel(db.Model):
    __tablename__ = "channels"

    channel_id  = db.Column(db.Integer, primary_key=True)
    name        = db.Column(db.String(120), unique=True, nullable=False)
    description = db.Column(db.String(500), nullable=True)
    color       = db.Column(db.String(20),  nullable=True, default="#4A90D9")
    created_at  = db.Column(db.DateTime,    default=datetime.utcnow)
    is_archived = db.Column(db.Boolean,     default=False)

    # cascade="all, delete-orphan" ensures that if a Channel object is deleted
    # via db.session.delete(channel) directly (e.g. in tests or future routes),
    # SQLAlchemy will automatically delete all associated Trade rows at the ORM
    # level before removing the channel row. The manual bulk-delete in
    # trade_storage.delete_channel() still runs first and is the primary path —
    # this cascade is a safety backstop that prevents orphaned trades if any
    # code path ever deletes a channel without going through trade_storage.
    trades = db.relationship(
        "Trade",
        backref="channel",
        lazy=True,
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<Channel {self.name}>"


class Trade(db.Model):
    __tablename__ = "trades"

    # ================================================================== #
    # PRIMARY KEY & FOREIGN KEY
    # ================================================================== #
    trade_id   = db.Column(db.Integer, primary_key=True)
    # index=True: every Trade query filters by channel_id. Without an explicit
    # index SQLite does a full table scan on every channel page load and export.
    # As the trades table grows (100s of rows across many channels) this
    # compounds — the index makes all filter_by(channel_id=...) O(log N).
    channel_id = db.Column(db.Integer, db.ForeignKey("channels.channel_id"), nullable=False, index=True)

    # ================================================================== #
    # USER-PROVIDED FIELDS
    # ================================================================== #

    symbol     = db.Column(db.String(20), nullable=False)
    trade_type = db.Column(db.String(30), nullable=False)
    # values: buy / sell / limit_buy / limit_sell / stop_buy / stop_sell

    entry_time   = db.Column(db.DateTime, nullable=False)
    entry_price  = db.Column(db.Float,    nullable=False)
    # Market orders: closing price at entry_time.
    # Pending orders: limit_price (actual fill price).

    stoploss_price   = db.Column(db.Float, nullable=False)
    takeprofit_price = db.Column(db.Float, nullable=True)   # NULL if user ran without a TP
    limit_price      = db.Column(db.Float, nullable=True)   # NULL for market orders

    # Breakeven config as the user set it on the form
    breakeven_active = db.Column(db.Boolean,    default=False)
    breakeven_type   = db.Column(db.String(10), nullable=True)   # 'rr' or 'pips'
    breakeven_value  = db.Column(db.Float,      nullable=True)

    # How the user expressed SL/TP: 'prices' / 'pips' / 'rr'
    input_type = db.Column(db.String(10), nullable=True)

    notes       = db.Column(db.String(1000), nullable=True)
    untp_notes  = db.Column(db.Text,         nullable=True)   # separate notes for UNTP walk view
    saved_at    = db.Column(db.DateTime,     default=datetime.utcnow)

    # ================================================================== #
    # TP TARGETS — BOTH FORMATS ALWAYS STORED. NULL if no TP provided.
    # ================================================================== #

    tp_rr_target   = db.Column(db.Float, nullable=True)
    tp_pips_target = db.Column(db.Float, nullable=True)

    # ================================================================== #
    # PENDING ORDER CONTEXT
    # ================================================================== #

    pending_trigger_time    = db.Column(db.DateTime, nullable=True)
    pending_wait_minutes    = db.Column(db.Float,    nullable=True)
    pending_order_triggered = db.Column(db.Boolean,  nullable=True)
    # True/False for pending orders; NULL for market orders

    # ================================================================== #
    # CORE EXCURSION — TRADE WALK ONLY
    # Measured from entry to the moment the trade closes.
    # ================================================================== #

    sl_distance_pips = db.Column(db.Float, nullable=True)
    # Distance entry→SL in pips. The 1R baseline for all RR calculations.

    # Peak MFE reached during the trade walk (entry to close).
    # For hit_tp: ≈ tp_rr_target (trade closed at TP level which is the peak).
    # For hit_sl/hit_be: whatever was reached before SL/BE fired.
    mfe_pips          = db.Column(db.Float, nullable=True)
    mfe_r             = db.Column(db.Float, nullable=True)
    mfe_at_close_pips = db.Column(db.Float, nullable=True)   # explicit alias of mfe_pips
    mfe_at_close_r    = db.Column(db.Float, nullable=True)   # explicit alias of mfe_r

    time_to_mfe_minutes = db.Column(db.Float, nullable=True)
    # Minutes from entry to peak MFE during trade walk.

    # Peak MAE reached during the trade walk.
    mae_pips            = db.Column(db.Float, nullable=True)
    mae_r               = db.Column(db.Float, nullable=True)
    time_to_mae_minutes = db.Column(db.Float, nullable=True)

    # ================================================================== #
    # RETRACEMENT AFTER PEAK
    # Distance from MFE peak to trade exit price.
    # hit_tp:    peak → TP exit (≈ 0 since TP closes at/near peak)
    # hit_sl/be: peak → SL/entry exit (the round-trip given back)
    # ================================================================== #

    retracement_from_mfe_pips = db.Column(db.Float, nullable=True)
    retracement_from_mfe_r    = db.Column(db.Float, nullable=True)

    # ================================================================== #
    # EXIT CONTEXT
    # ================================================================== #

    # Actual price at trade close:
    #   hit_tp  → takeprofit_price
    #   hit_sl  → stoploss_price
    #   hit_be  → entry_price  (SL moved to entry, price retraced there)
    #   open    → last candle close
    exit_price = db.Column(db.Float, nullable=True)

    candles_to_resolution = db.Column(db.Integer, nullable=True)

    # ================================================================== #
    # DIP / RE-ENTRY ANALYSIS
    # Adverse move BEFORE the first favourable candle from entry.
    # ================================================================== #

    dip_pips         = db.Column(db.Float,   nullable=True)
    dip_time_minutes = db.Column(db.Float,   nullable=True)
    dip_occurred     = db.Column(db.Boolean, nullable=True)

    # ================================================================== #
    # OUTCOME AND PNL — TRADE RESULTS
    # ================================================================== #

    # Trade outcome:
    #   hit_tp  → TP hit, trade closed at takeprofit_price
    #   hit_sl  → SL hit (no BE active or BE not triggered yet)
    #   hit_be  → BE triggered, then price retraced to entry_price
    #   open    → trade still running, TP set but not resolved
    #   none    → trade still running, no TP was set
    outcome_at_user_tp = db.Column(db.String(20), nullable=True)

    # Realised PnL in R-multiples. THE single source of truth for P&L.
    #   hit_tp  → +tp_rr_target  (e.g. +2.0 for a 2R TP)
    #   hit_sl  → -1.0           (exactly -1R, always)
    #   hit_be  → 0.0            (breakeven, no gain or loss)
    #   open    → NULL
    # Use pnl_r for equity curves, net RR, and expectancy — never derive
    # P&L from mfe fields or outcome strings.
    pnl_r = db.Column(db.Float, nullable=True)

    # Alias for pnl_r kept for compatibility.
    # Values: +tp_rr_target / -1.0 / 0.0 / NULL
    rr_at_user_tp = db.Column(db.Float, nullable=True)

    time_to_resolution_minutes = db.Column(db.Float, nullable=True)
    # Minutes from entry to trade close. NULL if still open.

    tp_was_reached = db.Column(db.Boolean, nullable=True)
    # True only for hit_tp. Equivalent to outcome_at_user_tp == 'hit_tp'.

    time_to_tp_minutes = db.Column(db.Float, nullable=True)
    # For hit_tp: equals time_to_resolution_minutes (TP IS the close event).
    # NULL for all other outcomes.

    peak_rr_at_close = db.Column(db.Float, nullable=True)
    # Peak MFE in R at the moment the trade closed.
    # For hit_tp:    ≈ tp_rr_target
    # For hit_sl/be: whatever MFE was floating when SL/BE fired

    # ================================================================== #
    # BREAKEVEN TRACKING
    # ================================================================== #

    breakeven_triggered            = db.Column(db.Boolean, default=False)
    breakeven_sl_price             = db.Column(db.Float,   nullable=True)
    # Always = entry_price when triggered (SL is moved to entry)
    breakeven_trigger_time_minutes = db.Column(db.Float,   nullable=True)
    mfe_at_breakeven_pips          = db.Column(db.Float,   nullable=True)
    mfe_at_breakeven_r             = db.Column(db.Float,   nullable=True)
    # MFE at the moment BE activated.
    mfe_after_be_pips = db.Column(db.Float, nullable=True)
    mfe_after_be_r    = db.Column(db.Float, nullable=True)
    # Additional MFE AFTER BE activated until the TRADE CLOSES (not UNTP stop).
    # Answers: "did my BE setting cut profits short?"

    # ================================================================== #
    # R MILESTONE TIMING
    # When (minutes from entry) did price first reach each R level.
    # NULL = never reached during the trade walk.
    # ================================================================== #

    time_to_0_5r_minutes = db.Column(db.Float, nullable=True)
    time_to_1r_minutes   = db.Column(db.Float, nullable=True)
    time_to_1_5r_minutes = db.Column(db.Float, nullable=True)
    time_to_2r_minutes   = db.Column(db.Float, nullable=True)
    time_to_3r_minutes   = db.Column(db.Float, nullable=True)
    time_to_4r_minutes   = db.Column(db.Float, nullable=True)
    time_to_5r_minutes   = db.Column(db.Float, nullable=True)

    # ================================================================== #
    # UNTP TIME-BOX SNAPSHOTS — 14 checkpoints (56 columns)
    #
    # UNTP = Unrealized TP — analytical continuation after trade closes.
    # Answers: "what could this trade have reached if held longer?"
    #
    # The UNTP walk starts at entry and continues even after trade closes.
    # It stops at the FIRST of:
    #   1. Original stoploss_price hit by price
    #   2. Entry price retraced (full round-trip — price back to entry)
    #   3. 504h cap (21 days)
    #
    # Per checkpoint — 4 fields:
    #
    #   mfe_at_Xh_r   peak MFE in R from entry to checkpoint (UNTP walk).
    #                 Frozen at the candle when UNTP stops. Does NOT reflect
    #                 any candle movement after the UNTP stop.
    #
    #   mae_at_Xh_r   peak MAE in R from entry to checkpoint (UNTP walk).
    #                 Same freeze semantics as mfe_at_Xh_r.
    #
    #   outcome_at_Xh TRADE outcome at this checkpoint:
    #                 'hit_tp'     = trade closed at TP before this checkpoint
    #                 'hit_sl'     = trade closed at SL before this checkpoint
    #                 'hit_be'     = trade closed at BE before this checkpoint
    #                 'still_open' = trade was still running at this checkpoint
    #
    #   alive_at_Xh   UNTP walk status at this checkpoint:
    #                 True  = UNTP walk still running (original SL and entry
    #                         NOT hit, cap not yet reached)
    #                 False = UNTP walk stopped
    #
    # IMPORTANT: outcome_at_Xh and alive_at_Xh track DIFFERENT things.
    # A trade can have outcome_at_4h='hit_tp' AND alive_at_4h=True —
    # meaning the trade closed at TP (e.g. at 3h) but UNTP is still running.
    #
    # DENOMINATOR for UNTP stats = alive_at_Xh=True trades only.
    # alive=False trades are inconclusive for that checkpoint — not losses.
    # ================================================================== #

    # 30 minutes
    mfe_at_30min_r   = db.Column(db.Float,      nullable=True)
    mae_at_30min_r   = db.Column(db.Float,      nullable=True)
    outcome_at_30min = db.Column(db.String(20), nullable=True)
    alive_at_30min   = db.Column(db.Boolean,    nullable=True)

    # 1 hour
    mfe_at_1h_r   = db.Column(db.Float,      nullable=True)
    mae_at_1h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_1h = db.Column(db.String(20), nullable=True)
    alive_at_1h   = db.Column(db.Boolean,    nullable=True)

    # 2 hours
    mfe_at_2h_r   = db.Column(db.Float,      nullable=True)
    mae_at_2h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_2h = db.Column(db.String(20), nullable=True)
    alive_at_2h   = db.Column(db.Boolean,    nullable=True)

    # 4 hours
    mfe_at_4h_r   = db.Column(db.Float,      nullable=True)
    mae_at_4h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_4h = db.Column(db.String(20), nullable=True)
    alive_at_4h   = db.Column(db.Boolean,    nullable=True)

    # 8 hours
    mfe_at_8h_r   = db.Column(db.Float,      nullable=True)
    mae_at_8h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_8h = db.Column(db.String(20), nullable=True)
    alive_at_8h   = db.Column(db.Boolean,    nullable=True)

    # 12 hours
    mfe_at_12h_r   = db.Column(db.Float,      nullable=True)
    mae_at_12h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_12h = db.Column(db.String(20), nullable=True)
    alive_at_12h   = db.Column(db.Boolean,    nullable=True)

    # 24 hours / 1 day
    mfe_at_24h_r   = db.Column(db.Float,      nullable=True)
    mae_at_24h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_24h = db.Column(db.String(20), nullable=True)
    alive_at_24h   = db.Column(db.Boolean,    nullable=True)

    # 48 hours / 2 days
    mfe_at_48h_r   = db.Column(db.Float,      nullable=True)
    mae_at_48h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_48h = db.Column(db.String(20), nullable=True)
    alive_at_48h   = db.Column(db.Boolean,    nullable=True)

    # 72 hours / 3 days
    mfe_at_72h_r   = db.Column(db.Float,      nullable=True)
    mae_at_72h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_72h = db.Column(db.String(20), nullable=True)
    alive_at_72h   = db.Column(db.Boolean,    nullable=True)

    # 120 hours / 5 days
    mfe_at_120h_r   = db.Column(db.Float,      nullable=True)
    mae_at_120h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_120h = db.Column(db.String(20), nullable=True)
    alive_at_120h   = db.Column(db.Boolean,    nullable=True)

    # 168 hours / 7 days
    mfe_at_168h_r   = db.Column(db.Float,      nullable=True)
    mae_at_168h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_168h = db.Column(db.String(20), nullable=True)
    alive_at_168h   = db.Column(db.Boolean,    nullable=True)

    # 240 hours / 10 days
    mfe_at_240h_r   = db.Column(db.Float,      nullable=True)
    mae_at_240h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_240h = db.Column(db.String(20), nullable=True)
    alive_at_240h   = db.Column(db.Boolean,    nullable=True)

    # 336 hours / 14 days
    mfe_at_336h_r   = db.Column(db.Float,      nullable=True)
    mae_at_336h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_336h = db.Column(db.String(20), nullable=True)
    alive_at_336h   = db.Column(db.Boolean,    nullable=True)

    # 504 hours / 21 days
    mfe_at_504h_r   = db.Column(db.Float,      nullable=True)
    mae_at_504h_r   = db.Column(db.Float,      nullable=True)
    outcome_at_504h = db.Column(db.String(20), nullable=True)
    alive_at_504h   = db.Column(db.Boolean,    nullable=True)

    # ================================================================== #
    # ENTRY QUALITY SIGNALS
    # ================================================================== #

    first_candle_direction = db.Column(db.String(10), nullable=True)
    # 'favour' / 'against' / 'neutral'

    consecutive_adverse_candles = db.Column(db.Integer, nullable=True)
    # Candles closing against trade before first favourable close

    avg_candle_size_pips_at_entry = db.Column(db.Float, nullable=True)
    # Average H-L range in pips over 10 candles before entry

    # ================================================================== #
    # CHANNEL STREAK CONTEXT
    # ================================================================== #

    # Positive = consecutive wins, negative = consecutive losses, 0 = first
    # win = hit_tp, loss = hit_sl or hit_be, skip = open/none
    channel_streak_at_save = db.Column(db.Integer, nullable=True)

    # ================================================================== #
    # SESSION / TIME CONTEXT
    # ================================================================== #

    entry_day_of_week = db.Column(db.Integer,    nullable=True)   # 0=Mon…4=Fri
    entry_hour        = db.Column(db.Integer,    nullable=True)
    entry_session     = db.Column(db.String(20), nullable=True)
    # 'asian' / 'london' / 'overlap' / 'new_york' / 'off_hours'

    # ================================================================== #
    # DATA INTEGRITY
    # ================================================================== #

    price_path_captured = db.Column(db.Boolean, default=False)
    # True  = both trade walk and UNTP walk completed; all fields reliable
    # False = walk failed; exclude from ALL statistics

    # ================================================================== #
    # GRANULAR UNTP PATH
    # JSON: [[elapsed_min, mfe_r, mae_r, untp_alive], ...]
    # 15-min sampled from entry. Continues through UNTP walk post-close.
    # Forced entries at: trade close event, UNTP walk stop event.
    # Capped at 504h (21 days). untp_alive=1 while UNTP running, 0 after.
    # Powers per-trade UNTP curve chart.
    # ================================================================== #
    mfe_path_json = db.Column(db.Text, nullable=True)

    # ================================================================== #
    # REPR & SERIALISATION
    # ================================================================== #

    def __repr__(self):
        return f"<Trade {self.trade_id} {self.symbol} {self.trade_type} {self.entry_time}>"

    def to_dict(self):
        return {
            "trade_id":                       self.trade_id,
            "channel_id":                     self.channel_id,
            "symbol":                         self.symbol,
            "trade_type":                     self.trade_type,
            "entry_time":                     self.entry_time.strftime("%Y-%m-%d %H:%M") if self.entry_time else None,
            "entry_price":                    self.entry_price,
            "stoploss_price":                 self.stoploss_price,
            "takeprofit_price":               self.takeprofit_price,
            "limit_price":                    self.limit_price,
            "breakeven_active":               self.breakeven_active,
            "breakeven_type":                 self.breakeven_type,
            "breakeven_value":                self.breakeven_value,
            "input_type":                     self.input_type,
            "notes":                          self.notes,
            "untp_notes":                     self.untp_notes,
            "saved_at":                       self.saved_at.strftime("%Y-%m-%d %H:%M") if self.saved_at else None,
            "tp_rr_target":                   self.tp_rr_target,
            "tp_pips_target":                 self.tp_pips_target,
            "pending_trigger_time":           self.pending_trigger_time.strftime("%Y-%m-%d %H:%M") if self.pending_trigger_time else None,
            "pending_wait_minutes":           self.pending_wait_minutes,
            "pending_order_triggered":        self.pending_order_triggered,
            "sl_distance_pips":               self.sl_distance_pips,
            "mfe_pips":                       self.mfe_pips,
            "mfe_r":                          self.mfe_r,
            "mfe_at_close_pips":              self.mfe_at_close_pips,
            "mfe_at_close_r":                 self.mfe_at_close_r,
            "time_to_mfe_minutes":            self.time_to_mfe_minutes,
            "mae_pips":                       self.mae_pips,
            "mae_r":                          self.mae_r,
            "time_to_mae_minutes":            self.time_to_mae_minutes,
            "retracement_from_mfe_pips":      self.retracement_from_mfe_pips,
            "retracement_from_mfe_r":         self.retracement_from_mfe_r,
            "exit_price":                     self.exit_price,
            "candles_to_resolution":          self.candles_to_resolution,
            "dip_pips":                       self.dip_pips,
            "dip_time_minutes":               self.dip_time_minutes,
            "dip_occurred":                   self.dip_occurred,
            "outcome_at_user_tp":             self.outcome_at_user_tp,
            "pnl_r":                          self.pnl_r,
            "rr_at_user_tp":                  self.rr_at_user_tp,
            "tp_was_reached":                 self.tp_was_reached,
            "time_to_tp_minutes":             self.time_to_tp_minutes,
            "peak_rr_at_close":               self.peak_rr_at_close,
            "time_to_resolution_minutes":     self.time_to_resolution_minutes,
            "breakeven_triggered":            self.breakeven_triggered,
            "breakeven_sl_price":             self.breakeven_sl_price,
            "breakeven_trigger_time_minutes": self.breakeven_trigger_time_minutes,
            "mfe_at_breakeven_pips":          self.mfe_at_breakeven_pips,
            "mfe_at_breakeven_r":             self.mfe_at_breakeven_r,
            "mfe_after_be_pips":              self.mfe_after_be_pips,
            "mfe_after_be_r":                 self.mfe_after_be_r,
            "time_to_0_5r_minutes":           self.time_to_0_5r_minutes,
            "time_to_1r_minutes":             self.time_to_1r_minutes,
            "time_to_1_5r_minutes":           self.time_to_1_5r_minutes,
            "time_to_2r_minutes":             self.time_to_2r_minutes,
            "time_to_3r_minutes":             self.time_to_3r_minutes,
            "time_to_4r_minutes":             self.time_to_4r_minutes,
            "time_to_5r_minutes":             self.time_to_5r_minutes,
            # UNTP snapshots — 14 checkpoints
            "mfe_at_30min_r":   self.mfe_at_30min_r,  "mae_at_30min_r":   self.mae_at_30min_r,  "outcome_at_30min": self.outcome_at_30min, "alive_at_30min": self.alive_at_30min,
            "mfe_at_1h_r":      self.mfe_at_1h_r,     "mae_at_1h_r":      self.mae_at_1h_r,     "outcome_at_1h":    self.outcome_at_1h,    "alive_at_1h":    self.alive_at_1h,
            "mfe_at_2h_r":      self.mfe_at_2h_r,     "mae_at_2h_r":      self.mae_at_2h_r,     "outcome_at_2h":    self.outcome_at_2h,    "alive_at_2h":    self.alive_at_2h,
            "mfe_at_4h_r":      self.mfe_at_4h_r,     "mae_at_4h_r":      self.mae_at_4h_r,     "outcome_at_4h":    self.outcome_at_4h,    "alive_at_4h":    self.alive_at_4h,
            "mfe_at_8h_r":      self.mfe_at_8h_r,     "mae_at_8h_r":      self.mae_at_8h_r,     "outcome_at_8h":    self.outcome_at_8h,    "alive_at_8h":    self.alive_at_8h,
            "mfe_at_12h_r":     self.mfe_at_12h_r,    "mae_at_12h_r":     self.mae_at_12h_r,    "outcome_at_12h":   self.outcome_at_12h,   "alive_at_12h":   self.alive_at_12h,
            "mfe_at_24h_r":     self.mfe_at_24h_r,    "mae_at_24h_r":     self.mae_at_24h_r,    "outcome_at_24h":   self.outcome_at_24h,   "alive_at_24h":   self.alive_at_24h,
            "mfe_at_48h_r":     self.mfe_at_48h_r,    "mae_at_48h_r":     self.mae_at_48h_r,    "outcome_at_48h":   self.outcome_at_48h,   "alive_at_48h":   self.alive_at_48h,
            "mfe_at_72h_r":     self.mfe_at_72h_r,    "mae_at_72h_r":     self.mae_at_72h_r,    "outcome_at_72h":   self.outcome_at_72h,   "alive_at_72h":   self.alive_at_72h,
            "mfe_at_120h_r":    self.mfe_at_120h_r,   "mae_at_120h_r":    self.mae_at_120h_r,   "outcome_at_120h":  self.outcome_at_120h,  "alive_at_120h":  self.alive_at_120h,
            "mfe_at_168h_r":    self.mfe_at_168h_r,   "mae_at_168h_r":    self.mae_at_168h_r,   "outcome_at_168h":  self.outcome_at_168h,  "alive_at_168h":  self.alive_at_168h,
            "mfe_at_240h_r":    self.mfe_at_240h_r,   "mae_at_240h_r":    self.mae_at_240h_r,   "outcome_at_240h":  self.outcome_at_240h,  "alive_at_240h":  self.alive_at_240h,
            "mfe_at_336h_r":    self.mfe_at_336h_r,   "mae_at_336h_r":    self.mae_at_336h_r,   "outcome_at_336h":  self.outcome_at_336h,  "alive_at_336h":  self.alive_at_336h,
            "mfe_at_504h_r":    self.mfe_at_504h_r,   "mae_at_504h_r":    self.mae_at_504h_r,   "outcome_at_504h":  self.outcome_at_504h,  "alive_at_504h":  self.alive_at_504h,
            # entry quality
            "first_candle_direction":         self.first_candle_direction,
            "consecutive_adverse_candles":    self.consecutive_adverse_candles,
            "avg_candle_size_pips_at_entry":  self.avg_candle_size_pips_at_entry,
            "channel_streak_at_save":         self.channel_streak_at_save,
            # session
            "entry_day_of_week":              self.entry_day_of_week,
            "entry_hour":                     self.entry_hour,
            "entry_session":                  self.entry_session,
            "price_path_captured":            self.price_path_captured,
            "mfe_path_json":                  self.mfe_path_json,
        }