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

IST = ZoneInfo("Asia/Kolkata")
CACHE = Path(__file__).resolve().parents[2] / "data" / "goldm_mcx_instruments.csv"
OPTION_WINGS = 3


def _expiry_date(value):
    try:
        return pd.to_datetime(value).date()
    except (TypeError, ValueError):
        return None


def _load_mcx_instruments():
    """Cache the daily MCX instrument master to avoid repeated downloads."""
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE.exists() and date.fromtimestamp(CACHE.stat().st_mtime) == date.today():
        frame = pd.read_csv(CACHE)
    else:
        kite = KiteConnect(api_key=KITE_API_KEY)
        kite.set_access_token(KITE_ACCESS_TOKEN)
        frame = pd.DataFrame(kite.instruments("MCX"))
        if frame.empty:
            raise RuntimeError("Kite returned an empty MCX instrument master")
        frame.to_csv(CACHE, index=False)
    required = {"instrument_token", "tradingsymbol", "expiry", "strike", "instrument_type", "exchange"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"MCX instrument master missing columns: {sorted(missing)}")
    frame["expiry_date"] = frame["expiry"].map(_expiry_date)
    frame["strike"] = pd.to_numeric(frame["strike"], errors="coerce")
    frame["instrument_token"] = pd.to_numeric(frame["instrument_token"], errors="coerce")
    frame = frame.dropna(subset=["instrument_token"])
    frame["instrument_token"] = frame["instrument_token"].astype(int)
    frame["tradingsymbol"] = frame["tradingsymbol"].astype(str)
    frame["instrument_type"] = frame["instrument_type"].astype(str).str.upper()
    return frame


class GoldMScanner:
    def __init__(self):
        self.lock = threading.RLock()
        self.ws = None
        self.master = None
        self.future = None
        self.option_expiry = None
        self.option_universe = pd.DataFrame()
        self.tracked = set()
        self.last_prices = {}
        self.latest_oi = {}
        self.engine = GoldMShadowEngine()
        self.option_universe_selected = pd.DataFrame()
        self.analytics = {}
        self.last_publish = 0.0
        self.state = {
            "connected": False, "future_symbol": None, "future_ltp": None,
            "future_expiry": None, "option_expiry": None, "options": [],
            "tracked_count": 0, "last_tick_time": None,
            "message": "GOLDM scanner initializing", "scoring_status": "SHADOW MODE: experimental scores only; not calibrated",
        }

    def _publish(self, message=None):
        with self.lock:
            payload = dict(self.state)
            if message:
                payload["message"] = message
        publish_goldm(payload)

    def _choose_contracts(self):
        today = datetime.now(IST).date()
        gold = self.master[
            self.master["tradingsymbol"].str.upper().str.startswith("GOLDM")
            & (self.master["exchange"].astype(str).str.upper() == "MCX")
            & self.master["expiry_date"].notna()
            & (self.master["expiry_date"] >= today)
        ].copy()
        futures = gold[gold["instrument_type"] == "FUT"].sort_values("expiry_date")
        if futures.empty:
            raise RuntimeError("No unexpired GOLDM futures contract found in the MCX instrument master")
        self.future = futures.iloc[0]
        options = gold[gold["instrument_type"].isin(["CE", "PE"])].copy()
        if not options.empty:
            option_expiries = sorted(options["expiry_date"].dropna().unique())
            if option_expiries:
                self.option_expiry = option_expiries[0]
                self.option_universe = options[options["expiry_date"] == self.option_expiry].copy()
            else:
                self.option_expiry = None
                self.option_universe = options.iloc[0:0]
        else:
            self.option_expiry = None
            self.option_universe = options

    def _nearby_options(self, future_price):
        options = self.option_universe
        if options.empty or future_price is None or future_price <= 0:
            return options.iloc[0:0]
        strikes = sorted(options["strike"].dropna().unique())
        if not strikes:
            return options.iloc[0:0]
        atm = min(strikes, key=lambda strike: abs(float(strike) - future_price))
        atm_idx = strikes.index(atm)
        allowed = set(strikes[max(0, atm_idx - OPTION_WINGS):atm_idx + OPTION_WINGS + 1])
        return options[options["strike"].isin(allowed)].copy()

    def _reconcile_options(self, future_price):
        if self.ws is None:
            return
        selected = self._nearby_options(future_price)
        future_token = int(self.future["instrument_token"])
        desired = {future_token} | set(selected["instrument_token"].astype(int).tolist())
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
        selected = getattr(self, "option_universe_selected", self.option_universe.iloc[0:0])
        rows = []
        future_price = self.state.get("future_ltp")
        for _, contract in selected.iterrows():
            token = int(contract["instrument_token"])
            tick = self.last_prices.get(token, {})
            expiry = contract["expiry_date"]
            analysis = self.analytics.get(token, {"score": None, "status": "WAITING_FOR_TICKS", "direction": "—", "components": {}})
            rows.append({
                "tradingsymbol": contract["tradingsymbol"],
                "option_type": contract["instrument_type"],
                "strike": None if pd.isna(contract["strike"]) else float(contract["strike"]),
                "expiry": str(contract["expiry_date"]),
                "ltp": tick.get("last_price"),
                "oi": tick.get("oi"),
                "volume": tick.get("volume"),
                "change_percent": tick.get("change_percent"),
                "score": analysis.get("score"),
                "score_status": analysis.get("status"),
                "direction": analysis.get("direction"),
                "underlying_direction": analysis.get("underlying_direction", analysis.get("direction")),
                "option_alignment": analysis.get("option_alignment", "UNKNOWN"),
                "delta": analysis.get("delta"),
                "iv_percent": analysis.get("iv_percent"),
                "gamma": analysis.get("gamma"),
                "components": analysis.get("components", {}),
                "observations": analysis.get("observations", 0),
            })
        rows.sort(key=lambda row: (row["strike"] or 0, row["option_type"]))
        return rows

    def on_connect(self, ws, response):
        self.ws = ws
        self.tracked = set()
        with self.lock:
            self.state.update({
                "connected": True,
                "future_symbol": self.future["tradingsymbol"],
                "future_expiry": str(self.future["expiry_date"]),
                "option_expiry": str(self.option_expiry) if self.option_expiry else None,
                "last_tick_time": None,
                "message": "Connected; waiting for futures/options ticks. Shadow scores are experimental and uncalibrated.",
            })
        ws.subscribe([int(self.future["instrument_token"])])
        ws.set_mode(ws.MODE_FULL, [int(self.future["instrument_token"])])
        self.tracked.add(int(self.future["instrument_token"]))
        self._publish()
        print(f"GOLDM WebSocket connected; futures={self.future['tradingsymbol']} expiry={self.future['expiry_date']}")
        if self.option_universe.empty:
            print("GOLDM OPTIONS: No matching CE/PE contracts found in current MCX instrument master; futures monitoring remains enabled.")
        else:
            print(f"GOLDM OPTIONS: Found {len(self.option_universe)} contracts for nearest expiry {self.option_expiry}; selecting near-ATM strikes after first futures tick.")

    def on_ticks(self, ws, ticks):
        future_token = int(self.future["instrument_token"])
        future_price = None
        with self.lock:
            for tick in ticks:
                token = int(tick.get("instrument_token", 0))
                self.last_prices[token] = {
                    "last_price": tick.get("last_price"),
                    "oi": tick.get("oi"),
                    "change_percent": tick.get("change"),
                    "volume": tick.get("volume_traded", tick.get("volume")),
                }
                if token == future_token:
                    future_price = tick.get("last_price")
            if future_price is None:
                future_price = self.state.get("future_ltp")
            if future_price is not None:
                self.state["future_ltp"] = float(future_price)
                self.engine.on_future(float(future_price))
            self.state["last_tick_time"] = datetime.now(IST).isoformat(timespec="seconds")
        if future_price and future_price > 0:
            try:
                self._reconcile_options(float(future_price))
            except Exception as exc:
                print(f"GOLDM subscription reconciliation error: {type(exc).__name__}: {exc}")
        with self.lock:
            for tick in ticks:
                token = int(tick.get("instrument_token", 0))
                if token == future_token:
                    continue
                selected = getattr(self, "option_universe_selected", self.option_universe.iloc[0:0])
                matches = selected[selected["instrument_token"] == token] if not selected.empty else selected
                if matches.empty:
                    continue
                contract = matches.iloc[0]
                market = self.last_prices.get(token, {})
                analysis = self.engine.evaluate(
                    token=token,
                    option_type=contract["instrument_type"],
                    strike=contract["strike"],
                    expiry=contract["expiry_date"],
                    premium=market.get("last_price"), oi=market.get("oi"),
                    volume=market.get("volume"), future_price=self.state.get("future_ltp"),
                    # Local receive timestamp keeps all observations on one consistent clock.
                    ts=time.time(),
                )
                if analysis.get("status") in {"NO_NEW_DATA", "DUPLICATE_TIMESTAMP"} and token in self.analytics:
                    # Preserve the last valid analysis; unchanged snapshots must not erase it.
                    pass
                else:
                    self.analytics[token] = analysis
            self.state["options"] = self._option_rows()
        self._publish()

    def on_error(self, ws, code, reason):
        self._publish(f"WebSocket error {code}: {reason}")
        print(f"GOLDM WebSocket error: {code} - {reason}")

    def on_close(self, ws, code, reason):
        with self.lock:
            self.state["connected"] = False
        self._publish(f"WebSocket closed {code}: {reason}")
        print(f"GOLDM WebSocket closed: {code} - {reason}")

    def run(self):
        if not KITE_API_KEY or not KITE_ACCESS_TOKEN:
            raise RuntimeError("Kite API key/access token missing; GOLDM scanner not started")
        self.master = _load_mcx_instruments()
        self._choose_contracts()
        print(f"GOLDM MCX instrument master loaded: {len(self.master)} rows")
        print("GOLDM scanner mode: monitoring-only; no orders are placed")
        kws = KiteTicker(KITE_API_KEY, KITE_ACCESS_TOKEN)
        self.ws = kws
        kws.on_connect = self.on_connect
        kws.on_ticks = self.on_ticks
        kws.on_error = self.on_error
        kws.on_close = self.on_close
        kws.connect(threaded=True)


def start_goldm_scanner():
    scanner = GoldMScanner()
    def runner():
        try:
            scanner.run()
        except Exception as exc:
            scanner._publish(f"GOLDM scanner startup failed: {type(exc).__name__}: {exc}")
            print(f"GOLDM scanner startup failed: {type(exc).__name__}: {exc}")
    thread = threading.Thread(target=runner, name="goldm-market-monitor", daemon=True)
    thread.start()
    return thread
