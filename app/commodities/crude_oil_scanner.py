"""
Standalone MCX Crude Oil futures signal scanner.
Monitoring only: this module does not place orders.
Run: python -m app.commodities.crude_oil_scanner
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv
from kiteconnect import KiteConnect, KiteTicker

load_dotenv()
IST = ZoneInfo("Asia/Kolkata")
LOG = logging.getLogger("crude_oil_scanner")

API_KEY = os.getenv("KITE_API_KEY", "").strip()
ACCESS_TOKEN = os.getenv("KITE_ACCESS_TOKEN", "").strip()
HOST = os.getenv("CRUDE_DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.getenv("CRUDE_DASHBOARD_PORT", "8767"))
CANDLE_MINUTES = 5
HISTORY_DAYS = 10
MIN_CANDLES = 55
ATR_PERIOD = 14
RISK_REWARD_1 = 1.0
RISK_REWARD_2 = 2.0
MAX_SIGNAL_AGE_MINUTES = 30

STATE_LOCK = threading.RLock()
STATE = {
    "app": "MCX Crude Oil Signal Engine",
    "connected": False,
    "status": "STARTING",
    "message": "Initializing scanner",
    "updated_at": None,
    "contract": None,
    "expiry": None,
    "instrument_token": None,
    "ltp": None,
    "day_change_percent": None,
    "candles_loaded": 0,
    "last_candle_time": None,
    "strategies": {
        "momentum": {"signal": "NO TRADE", "reason": "Waiting for candles"},
        "trend": {"signal": "NO TRADE", "reason": "Waiting for candles"},
    },
    "overall": {"signal": "NO TRADE", "reason": "Waiting for data"},
    "signals": deque(maxlen=50),
}
CANDLES = {}
LAST_TICK = {}
KITE = None
TICKER = None
FUTURE = None


def now_ist():
    return datetime.now(IST)


def iso(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def publish_status(status, message):
    with STATE_LOCK:
        STATE["status"] = status
        STATE["message"] = message
        STATE["updated_at"] = now_ist().isoformat()


def _to_python(value):
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if pd.isna(value):
        return None
    if isinstance(value, (datetime, )):
        return value.isoformat()
    return value


def snapshot():
    with STATE_LOCK:
        result = {k: v for k, v in STATE.items() if k not in ("signals", "_history")}
        result["strategies"] = dict(STATE["strategies"])
        result["overall"] = dict(STATE["overall"])
        result["signals"] = list(STATE["signals"])
        return result


def load_instruments(kite):
    """Load MCX master once; choose nearest unexpired CRUDEOIL future."""
    cache_dir = Path("data")
    cache_dir.mkdir(exist_ok=True)
    cache_file = cache_dir / "mcx_instruments.csv"
    df = None
    # Cache is intentionally refreshed once per calendar day to avoid repeated API calls.
    if cache_file.exists():
        age = time.time() - cache_file.stat().st_mtime
        if age < 20 * 60 * 60:
            try:
                df = pd.read_csv(cache_file)
            except Exception:
                df = None
    if df is None or df.empty:
        instruments = kite.instruments("MCX")
        df = pd.DataFrame(instruments)
        df.to_csv(cache_file, index=False)

    required = {"instrument_token", "tradingsymbol", "name", "instrument_type", "expiry"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"MCX instrument master missing columns: {sorted(missing)}")

    df["expiry_date"] = pd.to_datetime(df["expiry"], errors="coerce").dt.date
    today = now_ist().date()
    futures = df[
        df["name"].astype(str).str.upper().eq("CRUDEOIL")
        & df["instrument_type"].astype(str).str.upper().eq("FUT")
        & df["expiry_date"].notna()
        & (df["expiry_date"] >= today)
    ].copy()
    if futures.empty:
        # Some instrument masters may have a blank name but the expected symbol prefix.
        futures = df[
            df["tradingsymbol"].astype(str).str.upper().str.startswith("CRUDEOIL")
            & df["instrument_type"].astype(str).str.upper().eq("FUT")
            & df["expiry_date"].notna()
            & (df["expiry_date"] >= today)
        ].copy()
    if futures.empty:
        raise RuntimeError("No unexpired MCX CRUDEOIL futures contract found in Kite instrument master.")
    futures = futures.sort_values("expiry_date")
    return futures.iloc[0].to_dict()


def _normalise_candles(records):
    df = pd.DataFrame(records)
    if df.empty:
        return df
    df = df.rename(columns={"date": "time"})
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    if df["time"].dt.tz is None:
        df["time"] = df["time"].dt.tz_localize(IST)
    else:
        df["time"] = df["time"].dt.tz_convert(IST)
    df = df.dropna(subset=["time"]).drop_duplicates(subset=["time"]).sort_values("time")
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["time", "open", "high", "low", "close", "volume"]].dropna(subset=["close"]).reset_index(drop=True)


def fetch_history(kite, token):
    end = now_ist()
    start = end - timedelta(days=HISTORY_DAYS)
    records = kite.historical_data(
        instrument_token=int(token),
        from_date=start.replace(tzinfo=None),
        to_date=end.replace(tzinfo=None),
        interval="5minute",
        continuous=False,
        oi=False,
    )
    df = _normalise_candles(records)
    # Do not use the current incomplete candle as a confirmed candle.
    if not df.empty:
        cutoff = pd.Timestamp(now_ist()).floor("5min")
        df = df[df["time"] < cutoff].tail(500).reset_index(drop=True)
    return df


def _rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


def _enrich(df):
    x = df.copy()
    x["ema9"] = x["close"].ewm(span=9, adjust=False).mean()
    x["ema21"] = x["close"].ewm(span=21, adjust=False).mean()
    x["ema50"] = x["close"].ewm(span=50, adjust=False).mean()
    x["rsi"] = _rsi(x["close"])
    prev_close = x["close"].shift(1)
    tr = pd.concat([
        x["high"] - x["low"],
        (x["high"] - prev_close).abs(),
        (x["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    x["atr"] = tr.rolling(ATR_PERIOD, min_periods=ATR_PERIOD).mean()
    # Session VWAP, reset on each trading date. Zero-volume rows do not contribute.
    x["session"] = x["time"].dt.date
    typical = (x["high"] + x["low"] + x["close"]) / 3
    vol = x["volume"].clip(lower=0)
    x["pv"] = typical * vol
    x["cum_pv"] = x.groupby("session")["pv"].cumsum()
    x["cum_vol"] = vol.groupby(x["session"]).cumsum().replace(0, float("nan"))
    x["vwap"] = x["cum_pv"] / x["cum_vol"]
    x["vol_avg20"] = x["volume"].rolling(20, min_periods=5).mean()
    return x


def _risk_levels(side, entry, atr):
    # ATR-based protective stop and 1R/2R target; levels are informational only.
    risk = max(float(atr) * 1.2, abs(float(entry)) * 0.001)
    if side == "BUY":
        return {
            "entry": round(float(entry), 2),
            "stop_loss": round(float(entry) - risk, 2),
            "target_1": round(float(entry) + risk * RISK_REWARD_1, 2),
            "target_2": round(float(entry) + risk * RISK_REWARD_2, 2),
            "risk_points": round(risk, 2),
        }
    return {
        "entry": round(float(entry), 2),
        "stop_loss": round(float(entry) + risk, 2),
        "target_1": round(float(entry) - risk * RISK_REWARD_1, 2),
        "target_2": round(float(entry) - risk * RISK_REWARD_2, 2),
        "risk_points": round(risk, 2),
    }


def _strategy_result(signal, reason, row=None):
    result = {"signal": signal, "reason": reason, "candle_time": None}
    if row is not None:
        result["candle_time"] = iso(row["time"])
        result["close"] = _to_python(row["close"])
        result["vwap"] = _to_python(row["vwap"])
        result["rsi"] = _to_python(row["rsi"])
        result["atr"] = _to_python(row["atr"])
        if signal in ("BUY", "SELL") and pd.notna(row["atr"]) and row["atr"] > 0:
            result.update(_risk_levels(signal, row["close"], row["atr"]))
    return result


def evaluate_strategies(df):
    if len(df) < MIN_CANDLES:
        reason = f"Warm-up: need {MIN_CANDLES} completed 5-minute candles; have {len(df)}."
        return (
            _strategy_result("NO TRADE", reason),
            _strategy_result("NO TRADE", reason),
            _strategy_result("NO TRADE", reason),
        )

    x = _enrich(df)
    row = x.iloc[-1]
    prev = x.iloc[-2]
    if pd.isna(row["atr"]) or pd.isna(row["ema50"]):
        reason = "Waiting for valid indicator history."
        return (_strategy_result("NO TRADE", reason, row),
                _strategy_result("NO TRADE", reason, row),
                _strategy_result("NO TRADE", reason, row))

    # Momentum: close crosses the prior 20-candle range, with VWAP and relative-volume confirmation.
    lookback = x.iloc[-21:-1]
    high20 = lookback["high"].max()
    low20 = lookback["low"].min()
    vol_ok = pd.notna(row["vol_avg20"]) and row["vol_avg20"] > 0 and row["volume"] >= row["vol_avg20"] * 1.2
    if row["close"] > high20 and row["close"] > row["vwap"] and vol_ok:
        momentum = _strategy_result("BUY", "20-candle breakout above resistance; close above VWAP; volume >= 1.2x average.", row)
    elif row["close"] < low20 and row["close"] < row["vwap"] and vol_ok:
        momentum = _strategy_result("SELL", "20-candle breakdown below support; close below VWAP; volume >= 1.2x average.", row)
    else:
        momentum = _strategy_result("NO TRADE", "No confirmed range breakout with VWAP and volume confirmation.", row)

    # Trend: EMA alignment, price/VWAP confirmation and RSI not at an extreme.
    if row["ema9"] > row["ema21"] > row["ema50"] and row["close"] > row["vwap"] and 52 <= row["rsi"] <= 72:
        trend = _strategy_result("BUY", "EMA 9 > EMA 21 > EMA 50; close above VWAP; RSI confirms bullish momentum.", row)
    elif row["ema9"] < row["ema21"] < row["ema50"] and row["close"] < row["vwap"] and 28 <= row["rsi"] <= 48:
        trend = _strategy_result("SELL", "EMA 9 < EMA 21 < EMA 50; close below VWAP; RSI confirms bearish momentum.", row)
    else:
        trend = _strategy_result("NO TRADE", "EMA/VWAP/RSI trend conditions are not fully aligned.", row)

    active = [s["signal"] for s in (momentum, trend) if s["signal"] in ("BUY", "SELL")]
    if active == ["BUY", "BUY"]:
        overall = _strategy_result("BUY", "Both momentum and trend strategies agree.", row)
    elif active == ["SELL", "SELL"]:
        overall = _strategy_result("SELL", "Both momentum and trend strategies agree.", row)
    elif len(active) == 1:
        overall = _strategy_result("HOLD", "Only one strategy has a signal; wait for confirmation from the other strategy.", row)
    elif "BUY" in active and "SELL" in active:
        overall = _strategy_result("HOLD", "Strategies disagree; no combined directional signal.", row)
    else:
        overall = _strategy_result("NO TRADE", "No strategy has a confirmed signal.", row)
    return momentum, trend, overall


def update_from_candles(df):
    if df.empty:
        return
    # Ensure unique, sorted completed candle timestamps.
    df = df.drop_duplicates(subset=["time"]).sort_values("time").tail(500).reset_index(drop=True)
    momentum, trend, overall = evaluate_strategies(df)
    last = df.iloc[-1]
    with STATE_LOCK:
        STATE["candles_loaded"] = int(len(df))
        STATE["last_candle_time"] = iso(last["time"])
        STATE["strategies"] = {"momentum": momentum, "trend": trend}
        STATE["overall"] = overall
        STATE["updated_at"] = now_ist().isoformat()
        if overall["signal"] in ("BUY", "SELL"):
            prior = STATE["signals"][-1] if STATE["signals"] else None
            signature = (overall["signal"], overall.get("candle_time"))
            prior_sig = (prior.get("signal"), prior.get("candle_time")) if prior else None
            if signature != prior_sig:
                STATE["signals"].appendleft({
                    "signal": overall["signal"],
                    "candle_time": overall.get("candle_time"),
                    "entry": overall.get("entry"),
                    "stop_loss": overall.get("stop_loss"),
                    "target_1": overall.get("target_1"),
                    "target_2": overall.get("target_2"),
                    "reason": overall.get("reason"),
                })


def update_live_candle(tick):
    global CANDLES
    token = int(tick.get("instrument_token", 0))
    if not FUTURE or token != int(FUTURE["instrument_token"]):
        return
    price = float(tick.get("last_price") or 0)
    if price <= 0:
        return
    tick_time = tick.get("exchange_timestamp") or tick.get("last_trade_time") or now_ist()
    if tick_time.tzinfo is None:
        tick_time = tick_time.replace(tzinfo=IST)
    else:
        tick_time = tick_time.astimezone(IST)
    bucket = tick_time.replace(minute=(tick_time.minute // CANDLE_MINUTES) * CANDLE_MINUTES,
                               second=0, microsecond=0)
    bucket_key = bucket.isoformat()
    volume = float(tick.get("volume_traded") or 0)
    with STATE_LOCK:
        STATE["ltp"] = price
        STATE["updated_at"] = now_ist().isoformat()
        ohlc = tick.get("ohlc") or {}
        prev_close = float(ohlc.get("close") or 0)
        STATE["day_change_percent"] = ((price - prev_close) / prev_close * 100.0) if prev_close > 0 else None
        STATE["connected"] = True
        STATE["status"] = "LIVE"
        STATE["message"] = "Receiving live MCX Crude Oil futures ticks."
    if bucket_key not in CANDLES:
        CANDLES[bucket_key] = {
            "time": bucket, "open": price, "high": price, "low": price,
            "close": price, "volume": 0.0, "_volume_start": volume,
        }
    candle = CANDLES[bucket_key]
    candle["high"] = max(candle["high"], price)
    candle["low"] = min(candle["low"], price)
    candle["close"] = price
    candle["volume"] = max(0.0, volume - candle["_volume_start"])
    # On a new bucket, only publish candles that are definitely complete.
    keys = sorted(CANDLES)
    completed = []
    for key in keys:
        c = CANDLES[key]
        if c["time"] + timedelta(minutes=CANDLE_MINUTES) <= tick_time:
            completed.append({k: c[k] for k in ("time", "open", "high", "low", "close", "volume")})
    if completed:
        with STATE_LOCK:
            history = STATE.get("_history", [])
            by_time = {str(c["time"]): c for c in history}
            for c in completed:
                by_time[str(c["time"])] = c
            merged = sorted(by_time.values(), key=lambda c: c["time"])[-500:]
            STATE["_history"] = merged
            hist = pd.DataFrame(merged)
        update_from_candles(hist)
    # Keep the current partial candle; discard old in-memory candles.
    CANDLES = {k: v for k, v in CANDLES.items() if v["time"] >= tick_time - timedelta(hours=12)}


def on_connect(ws, response):
    try:
        token = int(FUTURE["instrument_token"])
        ws.subscribe([token])
        ws.set_mode(ws.MODE_FULL, [token])
        with STATE_LOCK:
            STATE["connected"] = True
        publish_status("CONNECTED", "WebSocket connected; waiting for live ticks.")
        LOG.info("Subscribed to %s (token %s)", FUTURE["tradingsymbol"], token)
    except Exception as exc:
        LOG.exception("Subscription failed")
        publish_status("ERROR", f"Subscription failed: {exc}")


def on_ticks(ws, ticks):
    for tick in ticks:
        try:
            update_live_candle(tick)
        except Exception:
            LOG.exception("Could not process live tick")


def on_error(ws, code, reason):
    publish_status("ERROR", f"Kite WebSocket error {code}: {reason}")


def on_close(ws, code, reason):
    with STATE_LOCK:
        STATE["connected"] = False
    publish_status("DISCONNECTED", f"WebSocket closed ({code}): {reason}")


def on_reconnect(ws, attempts_count):
    publish_status("RECONNECTING", f"WebSocket reconnect attempt {attempts_count}")


def on_noreconnect(ws):
    with STATE_LOCK:
        STATE["connected"] = False
    publish_status("ERROR", "WebSocket reconnect attempts exhausted; restart scanner if needed.")


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            path = Path(__file__).resolve().parents[2] / "dashboard" / "crude_oil.html"
            try:
                body = path.read_bytes()
            except OSError:
                self.send_error(500, "dashboard/crude_oil.html not found")
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        elif self.path == "/api/state":
            body = json.dumps(snapshot(), default=str).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
        else:
            self.send_error(404)
            return
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        LOG.info("Dashboard: " + fmt, *args)


def start_dashboard():
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True, name="crude-dashboard")
    thread.start()
    LOG.info("Dashboard available at http://%s:%s", HOST, PORT)
    return server


def main():
    global KITE, TICKER, FUTURE
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    start_dashboard()
    LOG.info("Starting standalone Crude Oil scanner (monitoring only; no orders).")
    if not API_KEY or not ACCESS_TOKEN:
        publish_status("CONFIG_ERROR", "Set KITE_API_KEY and KITE_ACCESS_TOKEN in .env.")
        raise SystemExit("Missing KITE_API_KEY or KITE_ACCESS_TOKEN in .env")
    KITE = KiteConnect(api_key=API_KEY)
    KITE.set_access_token(ACCESS_TOKEN)
    try:
        FUTURE = load_instruments(KITE)
        with STATE_LOCK:
            STATE["contract"] = str(FUTURE["tradingsymbol"])
            STATE["expiry"] = str(FUTURE["expiry_date"])
            STATE["instrument_token"] = int(FUTURE["instrument_token"])
        LOG.info("Selected MCX futures contract %s; expiry %s; token %s",
                 FUTURE["tradingsymbol"], FUTURE["expiry_date"], FUTURE["instrument_token"])
        publish_status("LOADING_HISTORY", "Loading historical 5-minute candles.")
        try:
            hist = fetch_history(KITE, FUTURE["instrument_token"])
            with STATE_LOCK:
                STATE["_history"] = [
                    {**row, "time": row["time"].to_pydatetime()}
                    for row in hist.to_dict("records")
                ]
            update_from_candles(hist)
            LOG.info("Loaded %s completed historical candles.", len(hist))
        except Exception as exc:
            LOG.warning("Historical candle load failed; waiting for live candles: %s", exc)
            with STATE_LOCK:
                STATE["_history"] = []
        TICKER = KiteTicker(API_KEY, ACCESS_TOKEN)
        TICKER.on_connect = on_connect
        TICKER.on_ticks = on_ticks
        TICKER.on_error = on_error
        TICKER.on_close = on_close
        TICKER.on_reconnect = on_reconnect
        TICKER.on_noreconnect = on_noreconnect
        publish_status("CONNECTING", "Connecting to Kite WebSocket.")
        TICKER.connect(threaded=False)
    except KeyboardInterrupt:
        LOG.info("Stopped by user.")
    except Exception as exc:
        publish_status("ERROR", f"{type(exc).__name__}: {exc}")
        LOG.exception("Crude Oil scanner failed")
        raise


if __name__ == "__main__":
    main()
