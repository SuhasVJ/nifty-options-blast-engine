
"""GOLDM futures/options market monitor. Monitoring only; never places orders."""

import threading
import time
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from kiteconnect import KiteConnect, KiteTicker

from app.config.settings import KITE_API_KEY, KITE_ACCESS_TOKEN
from app.dashboard.goldm_publisher import publish_goldm
from app.commodities.goldm_engine import GoldMShadowEngine
from app.commodities.goldm_strategy_comparison import compare_strategies


IST = ZoneInfo("Asia/Kolkata")
CACHE = Path(__file__).resolve().parents[2] / "data" / "goldm_mcx_instruments.csv"
OPTION_WINGS = 3
CONSOLE_LOG_INTERVAL_SECONDS = 10


def _expiry_date(value):
    try:
        return pd.to_datetime(value).date()
    except (TypeError, ValueError):
        return None


def _load_mcx_instruments():
    """Cache the daily MCX instrument master to avoid repeated downloads."""
    CACHE.parent.mkdir(parents=True, exist_ok=True)

    if (
            CACHE.exists()
            and date.fromtimestamp(CACHE.stat().st_mtime) == date.today()
    ):
        frame = pd.read_csv(CACHE)
    else:
        kite = KiteConnect(api_key=KITE_API_KEY)
        kite.set_access_token(KITE_ACCESS_TOKEN)

        frame = pd.DataFrame(kite.instruments("MCX"))

        if frame.empty:
            raise RuntimeError(
                "Kite returned an empty MCX instrument master"
            )

        frame.to_csv(CACHE, index=False)

    required = {
        "instrument_token",
        "tradingsymbol",
        "expiry",
        "strike",
        "instrument_type",
        "exchange",
    }

    missing = required - set(frame.columns)

    if missing:
        raise RuntimeError(
            f"MCX instrument master missing columns: {sorted(missing)}"
        )

    frame["expiry_date"] = frame["expiry"].map(_expiry_date)
    frame["strike"] = pd.to_numeric(frame["strike"], errors="coerce")
    frame["instrument_token"] = pd.to_numeric(
        frame["instrument_token"], errors="coerce"
    )

    frame = frame.dropna(subset=["instrument_token"])
    frame["instrument_token"] = frame["instrument_token"].astype(int)
    frame["tradingsymbol"] = frame["tradingsymbol"].astype(str)
    frame["instrument_type"] = (
        frame["instrument_type"].astype(str).str.upper()
    )

    return frame


class GoldMScanner:
    """Live GOLDM market scanner with experimental shadow analytics."""

    def __init__(self):
        self.lock = threading.RLock()
        self.ws = None
        self.master = None
        self.future = None
        self.option_expiry = None

        self.option_universe = pd.DataFrame()
        self.option_universe_selected = pd.DataFrame()

        self.tracked = set()
        self.last_prices = {}
        self.analytics = {}

        self.engine = GoldMShadowEngine()

        self.last_publish = 0.0
        self.last_console_log = 0.0

        self.state = {
            "connected": False,
            "future_symbol": None,
            "future_ltp": None,
            "future_expiry": None,
            "future_bid": None,
            "future_ask": None,
            "future_oi": None,
            "future_volume": None,
            "future_change_percent": None,
            "option_expiry": None,
            "options": [],
            "tracked_count": 0,
            "last_tick_time": None,
            "message": "GOLDM scanner initializing",
            "scoring_status": (
                "SHADOW MODE: experimental scores only; not calibrated"
            ),
            "strategy_comparison": {
                "status": "NO_TRADE",
                "best_candidate": None,
                "strategies": {},
            },
        }

    @staticmethod
    def _fmt(value, digits=2):
        """Format numeric values safely for console output."""
        try:
            if value is None:
                return "-"

            number = float(value)

            if not pd.notna(number):
                return "-"

            return f"{number:,.{digits}f}"

        except (TypeError, ValueError, OverflowError):
            return "-"

    def _publish(self, message=None):
        """Publish current scanner state to the GOLDM dashboard."""
        with self.lock:
            comparison = compare_strategies(
                list(self.engine.future_history),
                self._option_rows(),
                time.time(),
            )

            self.state["strategy_comparison"] = comparison

            payload = dict(self.state)

            if message:
                payload["message"] = message

        publish_goldm(payload)

    def _choose_contracts(self):
        """Choose the nearest unexpired GOLDM future and option expiry."""
        today = datetime.now(IST).date()

        gold = self.master[
            self.master["tradingsymbol"]
            .str.upper()
            .str.startswith("GOLDM")
            & (
                    self.master["exchange"].astype(str).str.upper()
                    == "MCX"
            )
            & self.master["expiry_date"].notna()
            & (self.master["expiry_date"] >= today)
            ].copy()

        futures = gold[
            gold["instrument_type"] == "FUT"
            ].sort_values("expiry_date")

        if futures.empty:
            raise RuntimeError(
                "No unexpired GOLDM futures contract found in "
                "the MCX instrument master"
            )

        self.future = futures.iloc[0]

        options = gold[
            gold["instrument_type"].isin(["CE", "PE"])
        ].copy()

        if not options.empty:
            expiries = sorted(
                options["expiry_date"].dropna().unique()
            )

            if expiries:
                self.option_expiry = expiries[0]
                self.option_universe = options[
                    options["expiry_date"] == self.option_expiry
                    ].copy()
            else:
                self.option_expiry = None
                self.option_universe = options.iloc[0:0]
        else:
            self.option_expiry = None
            self.option_universe = options

    def _nearby_options(self, future_price):
        """Select three available strikes on either side of ATM."""
        options = self.option_universe

        if (
                options.empty
                or future_price is None
                or future_price <= 0
        ):
            return options.iloc[0:0]

        strikes = sorted(options["strike"].dropna().unique())

        if not strikes:
            return options.iloc[0:0]

        atm = min(
            strikes,
            key=lambda strike: abs(float(strike) - future_price),
        )

        atm_idx = strikes.index(atm)

        allowed = set(
            strikes[
            max(0, atm_idx - OPTION_WINGS):
            atm_idx + OPTION_WINGS + 1
            ]
        )

        return options[options["strike"].isin(allowed)].copy()

    def _reconcile_options(self, future_price):
        """Subscribe to the current near-ATM options and unsubscribe stale ones."""
        if self.ws is None:
            return

        selected = self._nearby_options(future_price)
        future_token = int(self.future["instrument_token"])

        desired = {future_token} | set(
            selected["instrument_token"].astype(int).tolist()
        )

        remove = self.tracked - desired
        add = desired - self.tracked

        if remove:
            self.ws.unsubscribe(list(remove))

        if add:
            self.ws.subscribe(list(add))
            self.ws.set_mode(self.ws.MODE_FULL, list(add))

        self.tracked = desired
        self.option_universe_selected = selected

        self.state["tracked_count"] = len(desired)
        self.state["options"] = self._option_rows()

    def _option_rows(self):
        """Build dashboard and console rows from selected contracts."""
        selected = self.option_universe_selected

        rows = []

        for _, contract in selected.iterrows():
            token = int(contract["instrument_token"])
            tick = self.last_prices.get(token, {})
            analysis = self.analytics.get(
                token,
                {
                    "score": None,
                    "status": "WAITING_FOR_TICKS",
                    "direction": "—",
                    "components": {},
                },
            )

            bid = tick.get("best_bid")
            ask = tick.get("best_ask")

            spread_percent = None

            try:
                if (
                        bid is not None
                        and ask is not None
                        and float(bid) > 0
                        and float(ask) >= float(bid)
                ):
                    midpoint = (float(bid) + float(ask)) / 2.0

                    if midpoint > 0:
                        spread_percent = (
                                (float(ask) - float(bid))
                                / midpoint
                                * 100.0
                        )
            except (TypeError, ValueError, ZeroDivisionError):
                spread_percent = None

            strike = contract["strike"]

            rows.append({
                "tradingsymbol": contract["tradingsymbol"],
                "option_type": contract["instrument_type"],
                "strike": (
                    None if pd.isna(strike) else float(strike)
                ),
                "expiry": str(contract["expiry_date"]),
                "ltp": tick.get("last_price"),
                "best_bid": bid,
                "best_ask": ask,
                "spread_percent": spread_percent,
                "oi": tick.get("oi"),
                "volume": tick.get("volume"),
                "change_percent": tick.get("change_percent"),
                "score": analysis.get("score"),
                "score_status": analysis.get("status"),
                "direction": analysis.get("direction"),
                "underlying_direction": analysis.get(
                    "underlying_direction",
                    analysis.get("direction"),
                ),
                "option_alignment": analysis.get(
                    "option_alignment", "UNKNOWN"
                ),
                "delta": analysis.get("delta"),
                "iv_percent": analysis.get("iv_percent"),
                "gamma": analysis.get("gamma"),
                "components": analysis.get("components", {}),
                "observations": analysis.get("observations", 0),
            })

        rows.sort(
            key=lambda row: (
                row["strike"] or 0,
                row["option_type"],
            )
        )

        return rows

    def _print_scan_snapshot(self, tick_count):
        """Print a readable market snapshot at most every ten seconds."""
        now = time.time()

        if now - self.last_console_log < CONSOLE_LOG_INTERVAL_SECONDS:
            return

        self.last_console_log = now

        with self.lock:
            state = dict(self.state)
            rows = list(self.state.get("options", []))
            comparison = dict(
                self.state.get("strategy_comparison", {})
            )

        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")

        print(
            f"\n{'=' * 120}\n"
            f"[{timestamp} IST] GOLDM LIVE MARKET SCAN\n"
            f"{'=' * 120}",
            flush=True,
        )

        print(
            f"CONNECTION: {'CONNECTED' if state.get('connected') else 'DISCONNECTED'}"
            f" | Batch ticks: {tick_count}"
            f" | Tracked instruments: {state.get('tracked_count', 0)}",
            flush=True,
        )

        print(
            f"FUTURE: {state.get('future_symbol')}"
            f" | Expiry: {state.get('future_expiry')}"
            f" | LTP: {self._fmt(state.get('future_ltp'))}"
            f" | Change: {self._fmt(state.get('future_change_percent'))}%"
            f" | Bid: {self._fmt(state.get('future_bid'))}"
            f" | Ask: {self._fmt(state.get('future_ask'))}"
            f" | OI: {self._fmt(state.get('future_oi'), 0)}"
            f" | Volume: {self._fmt(state.get('future_volume'), 0)}",
            flush=True,
        )

        print(
            f"OPTIONS EXPIRY: {state.get('option_expiry')}"
            f" | Selected contracts: {len(rows)}",
            flush=True,
        )

        print("-" * 120, flush=True)

        print(
            "SYMBOL | TYPE | STRIKE | LTP | BID | ASK | "
            "SPREAD% | CHANGE% | OI | VOLUME | DELTA | IV% | "
            "GAMMA | SCORE | ANALYTICS STATUS",
            flush=True,
        )

        for row in rows:
            print(
                f"{row.get('tradingsymbol', '-')}"
                f" | {row.get('option_type', '-')}"
                f" | {self._fmt(row.get('strike'), 0)}"
                f" | {self._fmt(row.get('ltp'))}"
                f" | {self._fmt(row.get('best_bid'))}"
                f" | {self._fmt(row.get('best_ask'))}"
                f" | {self._fmt(row.get('spread_percent'))}"
                f" | {self._fmt(row.get('change_percent'))}"
                f" | {self._fmt(row.get('oi'), 0)}"
                f" | {self._fmt(row.get('volume'), 0)}"
                f" | {self._fmt(row.get('delta'), 3)}"
                f" | {self._fmt(row.get('iv_percent'))}"
                f" | {self._fmt(row.get('gamma'), 6)}"
                f" | {self._fmt(row.get('score'))}"
                f" | {row.get('score_status', '-')}",
                flush=True,
            )

        strategies = comparison.get("strategies", {})

        print("-" * 120, flush=True)
        print("STRATEGY COMPARISON", flush=True)

        for key in ("momentum", "trend"):
            strategy = strategies.get(key, {})

            print(
                f"{key.upper()}"
                f" | Score: {self._fmt(strategy.get('score'))}"
                f" | Direction: {strategy.get('direction', '-')}"
                f" | Status: {strategy.get('status', '-')}"
                f" | Candidate: {strategy.get('candidate_status', '-')}"
                f" | Reason: {strategy.get('reason', '-')}",
                flush=True,
            )

            candidate = strategy.get("candidate")

            if candidate:
                print(
                    f"  SHADOW CANDIDATE: "
                    f"{candidate.get('tradingsymbol')}"
                    f" | Combined score: "
                    f"{self._fmt(candidate.get('score'))}"
                    f" | Option score: "
                    f"{self._fmt(candidate.get('option_score'))}"
                    f" | LTP: {self._fmt(candidate.get('ltp'))}"
                    f" | Delta: {self._fmt(candidate.get('delta'), 3)}"
                    f" | IV: {self._fmt(candidate.get('iv_percent'))}%",
                    flush=True,
                )

            for reason in strategy.get("rejections", [])[:3]:
                print(f"  FILTER: {reason}", flush=True)

        best = comparison.get("best_candidate")

        print("-" * 120, flush=True)

        if best:
            print(
                "BEST ELIGIBLE SHADOW CANDIDATE"
                f" | {best.get('tradingsymbol')}"
                f" | Strategy: {best.get('strategy')}"
                f" | Direction: {best.get('direction')}"
                f" | Combined score: {self._fmt(best.get('score'))}",
                flush=True,
            )
        else:
            print(
                "BEST ELIGIBLE SHADOW CANDIDATE: None currently eligible",
                flush=True,
            )

            print(
                f"Scanner status: {comparison.get('status', 'NO_TRADE')}"
                f" | {comparison.get('message', '')}",
                flush=True,
            )

        print(
            "MODE: MONITORING ONLY"
            " | Scores are experimental, uncalibrated rankings."
            " | NO ORDERS ARE PLACED.",
            flush=True,
        )

        print("=" * 120, flush=True)

    def on_connect(self, ws, response):
        """Subscribe to the selected future and wait for its first tick."""
        self.ws = ws
        self.tracked = set()

        future_token = int(self.future["instrument_token"])

        with self.lock:
            self.state.update({
                "connected": True,
                "future_symbol": self.future["tradingsymbol"],
                "future_expiry": str(self.future["expiry_date"]),
                "option_expiry": (
                    str(self.option_expiry)
                    if self.option_expiry
                    else None
                ),
                "last_tick_time": None,
                "message": (
                    "Connected; waiting for futures/options ticks. "
                    "Shadow scores are experimental and uncalibrated."
                ),
            })

        ws.subscribe([future_token])
        ws.set_mode(ws.MODE_FULL, [future_token])

        self.tracked.add(future_token)

        self._publish()

        print(
            f"GOLDM WebSocket connected; "
            f"futures={self.future['tradingsymbol']} "
            f"expiry={self.future['expiry_date']}",
            flush=True,
        )

        if self.option_universe.empty:
            print(
                "GOLDM OPTIONS: No matching CE/PE contracts found. "
                "Futures monitoring remains enabled.",
                flush=True,
            )
        else:
            print(
                f"GOLDM OPTIONS: Found {len(self.option_universe)} "
                f"contracts for nearest expiry {self.option_expiry}; "
                "selecting near-ATM strikes after first futures tick.",
                flush=True,
            )

    def on_ticks(self, ws, ticks):
        """Process market ticks, update analytics and publish live state."""
        if not ticks:
            return

        future_token = int(self.future["instrument_token"])
        future_price = None
        future_tick_received = False
        now_ts = time.time()

        with self.lock:
            # First, cache every tick in this callback.
            # Check the future token inside the loop so a futures tick
            # is not missed when it is not the last item in the batch.
            for tick in ticks:
                token = int(tick.get("instrument_token", 0))
                depth = tick.get("depth") or {}

                buy_levels = depth.get("buy") or [{}]
                sell_levels = depth.get("sell") or [{}]

                self.last_prices[token] = {
                    "last_price": tick.get("last_price"),
                    "oi": tick.get("oi"),
                    "change_percent": tick.get("change"),
                    "volume": tick.get(
                        "volume_traded",
                        tick.get("volume"),
                    ),
                    "best_bid": buy_levels[0].get("price"),
                    "best_ask": sell_levels[0].get("price"),
                }

                if token == future_token:
                    tick_price = tick.get("last_price")

                    if (
                            tick_price is not None
                            and float(tick_price) > 0
                    ):
                        future_price = float(tick_price)
                        future_tick_received = True

                        market = self.last_prices[token]

                        self.state.update({
                            "future_ltp": future_price,
                            "future_bid": market.get("best_bid"),
                            "future_ask": market.get("best_ask"),
                            "future_oi": market.get("oi"),
                            "future_volume": market.get("volume"),
                            "future_change_percent": market.get(
                                "change_percent"
                            ),
                        })

            if future_tick_received:
                # Add to strategy history only on a genuine futures tick.
                self.engine.on_future(future_price, ts=now_ts)
            else:
                # Option ticks can use the last known futures price,
                # but must not create artificial futures observations.
                future_price = self.state.get("future_ltp")

            self.state["last_tick_time"] = datetime.now(
                IST
            ).isoformat(timespec="seconds")

        # Update subscriptions using the latest known futures price.
        if future_price is not None and future_price > 0:
            try:
                self._reconcile_options(float(future_price))
            except Exception as exc:
                print(
                    "GOLDM subscription reconciliation error: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

        # Evaluate only selected option contracts.
        with self.lock:
            selected = self.option_universe_selected

            for tick in ticks:
                token = int(tick.get("instrument_token", 0))

                if token == future_token:
                    continue

                if selected.empty:
                    continue

                matches = selected[
                    selected["instrument_token"] == token
                    ]

                if matches.empty:
                    continue

                contract = matches.iloc[0]
                market = self.last_prices.get(token, {})

                analysis = self.engine.evaluate(
                    token=token,
                    option_type=contract["instrument_type"],
                    strike=contract["strike"],
                    expiry=contract["expiry_date"],
                    premium=market.get("last_price"),
                    oi=market.get("oi"),
                    volume=market.get("volume"),
                    future_price=self.state.get("future_ltp"),
                    ts=now_ts,
                )

                if (
                        analysis.get("status")
                        in {"NO_NEW_DATA", "DUPLICATE_TIMESTAMP"}
                        and token in self.analytics
                ):
                    # Preserve the last valid analytics result.
                    pass
                else:
                    self.analytics[token] = analysis

            self.state["options"] = self._option_rows()

        # Publish dashboard data before building the console snapshot,
        # so the snapshot contains the latest strategy comparison.
        self._publish()
        self._print_scan_snapshot(len(ticks))

    def on_error(self, ws, code, reason):
        message = f"WebSocket error {code}: {reason}"

        self._publish(message)

        print(f"GOLDM {message}", flush=True)

    def on_close(self, ws, code, reason):
        with self.lock:
            self.state["connected"] = False

        message = f"WebSocket closed {code}: {reason}"

        self._publish(message)

        print(f"GOLDM {message}", flush=True)

    def run(self):
        """Load instruments and start the live WebSocket connection."""
        if not KITE_API_KEY or not KITE_ACCESS_TOKEN:
            raise RuntimeError(
                "Kite API key/access token missing; "
                "GOLDM scanner not started"
            )

        self.master = _load_mcx_instruments()
        self._choose_contracts()

        print(
            f"GOLDM MCX instrument master loaded: {len(self.master)} rows",
            flush=True,
        )

        print(
            "GOLDM scanner mode: monitoring-only; no orders are placed",
            flush=True,
        )

        kws = KiteTicker(KITE_API_KEY, KITE_ACCESS_TOKEN)
        self.ws = kws

        kws.on_connect = self.on_connect
        kws.on_ticks = self.on_ticks
        kws.on_error = self.on_error
        kws.on_close = self.on_close

        kws.connect(threaded=True)


def start_goldm_scanner():
    """Start the scanner in a daemon thread."""
    scanner = GoldMScanner()

    def runner():
        try:
            scanner.run()
        except Exception as exc:
            scanner._publish(
                f"GOLDM scanner startup failed: "
                f"{type(exc).__name__}: {exc}"
            )

            print(
                "GOLDM scanner startup failed: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    thread = threading.Thread(
        target=runner,
        name="goldm-market-monitor",
        daemon=True,
    )

    thread.start()

    return thread
