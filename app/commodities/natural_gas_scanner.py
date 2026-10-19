"""MCX Natural Gas futures scanner. Signal-only; never places orders."""
import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from kiteconnect import KiteConnect

from app.config.settings import KITE_API_KEY, KITE_ACCESS_TOKEN
from app.commodities.natural_gas_engine import add_indicators, evaluate_latest
from app.dashboard.natural_gas_publisher import publish_natural_gas

IST = ZoneInfo("Asia/Kolkata")
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "mcx_instruments.csv"
HISTORY = ROOT / "data" / "natural_gas_signal_history.csv"
POLL_SECONDS = 60
LOOKBACK_DAYS = 15


def _date(value):
    try:
        return pd.to_datetime(value).date()
    except (TypeError, ValueError):
        return None


def load_instruments(kite):
    """Refresh the MCX instrument master once per local trading day."""
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE.exists() and datetime.fromtimestamp(CACHE.stat().st_mtime, IST).date() == datetime.now(IST).date():
        frame = pd.read_csv(CACHE)
    else:
        frame = pd.DataFrame(kite.instruments("MCX"))
        if frame.empty:
            raise RuntimeError("Kite returned an empty MCX instrument master")
        frame.to_csv(CACHE, index=False)
    required = {"instrument_token", "tradingsymbol", "expiry", "instrument_type", "exchange", "name"}
    missing = required - set(frame.columns)
    if missing:
        raise RuntimeError(f"MCX instrument master missing columns: {sorted(missing)}")
    frame["expiry_date"] = frame["expiry"].map(_date)
    frame["instrument_type"] = frame["instrument_type"].astype(str).str.upper()
    frame["exchange"] = frame["exchange"].astype(str).str.upper()
    frame["name_upper"] = frame["name"].astype(str).str.upper()
    frame["symbol_upper"] = frame["tradingsymbol"].astype(str).str.upper()
    return frame


def choose_nearest_future(master):
    today = datetime.now(IST).date()
    mask = (
        (master["exchange"] == "MCX")
        & (master["instrument_type"] == "FUT")
        & master["expiry_date"].notna()
        & (master["expiry_date"] >= today)
        & (
            master["name_upper"].str.contains("NATURAL GAS", regex=False)
            | master["symbol_upper"].str.startswith("NATURALGAS")
        )
        & ~master["symbol_upper"].str.contains("MINI", regex=False)
    )
    contracts = master.loc[mask].sort_values("expiry_date")
    if contracts.empty:
        raise RuntimeError("No unexpired standard MCX Natural Gas futures contract found")
    return contracts.iloc[0]


def _candles(kite, token, interval, days=LOOKBACK_DAYS):
    now = datetime.now(IST)
    start = now - timedelta(days=days)
    raw = kite.historical_data(int(token), start, now, interval, continuous=False, oi=False)
    frame = pd.DataFrame(raw)
    if frame.empty:
        return frame
    frame = frame.rename(columns={"date": "date"})
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    if frame["date"].dt.tz is None:
        frame["date"] = frame["date"].dt.tz_localize(IST)
    else:
        frame["date"] = frame["date"].dt.tz_convert(IST)
    duration = {"5minute": timedelta(minutes=5), "15minute": timedelta(minutes=15),
                "60minute": timedelta(minutes=60)}[interval]
    # Historical candle timestamps represent candle start; exclude the still-forming candle.
    frame = frame[frame["date"] + duration <= pd.Timestamp(now)]
    return frame[["date", "open", "high", "low", "close", "volume"]].dropna().sort_values("date")


class NaturalGasScanner:
    def __init__(self):
        if not KITE_API_KEY or not KITE_ACCESS_TOKEN:
            raise RuntimeError("Set KITE_API_KEY and KITE_ACCESS_TOKEN in .env before starting the scanner")
        self.kite = KiteConnect(api_key=KITE_API_KEY)
        self.kite.set_access_token(KITE_ACCESS_TOKEN)
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.state = {
            "connected": False, "instrument": "MCX Natural Gas futures", "symbol": None,
            "expiry": None, "ltp": None, "last_data_time": None, "updated_at": None,
            "status": "INITIALIZING", "message": "Loading MCX instrument master",
            "signals": {"intraday": None, "swing": None}, "history": [],
            "data_source": "Zerodha Kite Connect historical candles",
        }
        self.contract = None
        self.last_signal_keys = set()
        self._load_history()

    def _load_history(self):
        if not HISTORY.exists():
            return
        try:
            frame = pd.read_csv(HISTORY).tail(100)
            records = frame.where(pd.notna(frame), None).to_dict(orient="records")
            for record in records:
                raw_reasons = record.get("reasons")
                if isinstance(raw_reasons, str):
                    try:
                        record["reasons"] = json.loads(raw_reasons)
                    except (ValueError, TypeError):
                        record["reasons"] = [raw_reasons] if raw_reasons else []
                self.last_signal_keys.add((
                    record.get("timeframe"), str(record.get("timestamp")),
                    record.get("direction"), record.get("symbol")
                ))
            self.state["history"] = list(reversed(records))
        except (OSError, ValueError, pd.errors.ParserError) as exc:
            print(f"Natural Gas signal history could not be loaded: {type(exc).__name__}: {exc}")

    def _publish(self, **updates):
        with self.lock:
            self.state.update(updates)
            payload = dict(self.state)
        publish_natural_gas(payload)

    def _persist_signal(self, signal, symbol, expiry):
        HISTORY.parent.mkdir(parents=True, exist_ok=True)
        record = dict(signal)
        record.update({"symbol": symbol, "expiry": str(expiry), "strategy_version": "balanced-v1"})
        key = (record.get("timeframe"), record.get("timestamp"), record.get("direction"), symbol)
        if key in self.last_signal_keys:
            return
        self.last_signal_keys.add(key)
        record["reasons"] = json.dumps(record.get("reasons", []), ensure_ascii=False)
        frame = pd.DataFrame([record])
        frame.to_csv(HISTORY, mode="a", header=not HISTORY.exists(), index=False)
        with self.lock:
            self.state["history"] = ([record] + self.state["history"])[:100]

    def run_once(self):
        master = load_instruments(self.kite)
        contract = choose_nearest_future(master)
        changed = self.contract is None or int(contract["instrument_token"]) != int(self.contract["instrument_token"])
        self.contract = contract
        token = int(contract["instrument_token"])
        now = datetime.now(IST)
        results = {}
        ltp = None
        for timeframe, interval in (("intraday", "5minute"), ("swing", "15minute")):
            candles = _candles(self.kite, token, interval)
            if candles.empty:
                results[timeframe] = {"direction": "WAIT", "status": "NO_CANDLES",
                                      "reasons": ["No completed historical candles returned"]}
                continue
            signal = evaluate_latest(candles, timeframe).to_dict()
            if timeframe == "swing" and signal.get("direction") in {"BUY", "SELL"}:
                hourly = _candles(self.kite, token, "60minute")
                if hourly.empty or len(hourly) < 35:
                    signal.update({"direction": "WAIT", "entry": None, "stop_loss": None,
                                   "target_1": None, "target_2": None, "risk_reward_target_1": None,
                                   "status": "WAITING_FOR_HOURLY_CONFIRMATION",
                                   "reasons": ["15-minute setup found; insufficient completed 60-minute candles for trend confirmation"]})
                else:
                    trend = add_indicators(hourly).iloc[-1]
                    aligned = (
                        float(trend["ema9"]) > float(trend["ema21"]) and float(trend["close"]) > float(trend["vwap"])
                        if signal["direction"] == "BUY" else
                        float(trend["ema9"]) < float(trend["ema21"]) and float(trend["close"]) < float(trend["vwap"])
                    )
                    if not aligned:
                        signal.update({"direction": "WAIT", "entry": None, "stop_loss": None,
                                       "target_1": None, "target_2": None, "risk_reward_target_1": None,
                                       "status": "HOURLY_TREND_NOT_CONFIRMED",
                                       "reasons": ["15-minute setup rejected: 60-minute EMA trend and VWAP do not confirm direction"]})
                    else:
                        signal["reasons"] = list(signal.get("reasons", [])) + ["Confirmed by 60-minute EMA trend and VWAP"]
            results[timeframe] = signal
            ltp = float(candles.iloc[-1]["close"])
            if signal.get("timestamp"):
                self._persist_signal(signal, contract["tradingsymbol"], contract["expiry_date"])
        self._publish(
            connected=True, symbol=str(contract["tradingsymbol"]), expiry=str(contract["expiry_date"]),
            ltp=ltp, last_data_time=now.isoformat(timespec="seconds"),
            updated_at=now.isoformat(timespec="seconds"), status="CONNECTED",
            message=("Contract changed; new expiry selected" if changed and ltp is not None
                     else "Completed-candle analysis updated"),
            signals=results,
        )

    def run_forever(self):
        self._publish(status="CONNECTING", message="Connecting to Kite Connect")
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:
                self._publish(status="ERROR", message=f"{type(exc).__name__}: {exc}",
                              updated_at=datetime.now(IST).isoformat(timespec="seconds"))
                print(f"Natural Gas scanner error: {type(exc).__name__}: {exc}")
            self.stop_event.wait(POLL_SECONDS)

    def stop(self):
        self.stop_event.set()


def start_natural_gas_scanner():
    scanner = NaturalGasScanner()
    thread = threading.Thread(target=scanner.run_forever, name="natural-gas-scanner", daemon=True)
    thread.start()
    return scanner
