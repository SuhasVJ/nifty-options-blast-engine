"""Deterministic swing indicators and explainable signals; never places orders."""
from __future__ import annotations

import json
import logging
from pathlib import Path
import pandas as pd

from .config import settings

LOG = logging.getLogger("seven_horses.signals")


def load_candles(path: Path) -> pd.DataFrame:
    frame = pd.DataFrame(json.loads(path.read_text(encoding="utf-8")))
    if frame.empty:
        raise ValueError(f"No candles found in {path}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp").set_index("timestamp")
    return frame


def add_indicators(frame: pd.DataFrame) -> pd.DataFrame:
    """Compute close-of-day indicators. Signals are for research, not advice."""
    df = frame.copy()
    df["ema20"] = df["close"].ewm(span=20, adjust=False, min_periods=20).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False, min_periods=50).mean()
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, float("nan"))
    df["rsi14"] = 100 - (100 / (1 + rs))
    df.loc[(loss == 0) & (gain > 0), "rsi14"] = 100
    df["return20"] = df["close"].pct_change(20)
    previous_close = df["close"].shift(1)
    true_range = pd.concat([
        df["high"] - df["low"],
        (df["high"] - previous_close).abs(),
        (df["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    df["volume_avg20"] = df["volume"].rolling(20, min_periods=20).mean()
    df["relative_volume"] = df["volume"] / df["volume_avg20"].replace(0, float("nan"))
    return df


def classify_latest(df: pd.DataFrame) -> dict:
    """Classify latest completed daily candle with transparent, fixed rules."""
    valid = df.dropna(subset=["ema20", "ema50", "rsi14", "return20", "atr14", "relative_volume"])
    if valid.empty:
        return {"signal": "INSUFFICIENT_DATA", "reasons": ["Need at least 50 valid daily candles and indicator warm-up."]}
    row = valid.iloc[-1]
    reasons = []
    trend_up = row["close"] > row["ema50"] and row["ema20"] > row["ema50"]
    momentum_up = row["return20"] > 0 and 50 <= row["rsi14"] <= 70
    volume_ok = row["relative_volume"] >= 1.0
    exit_trend = row["close"] < row["ema50"] or row["ema20"] < row["ema50"] or row["rsi14"] < 45

    if trend_up:
        reasons.append("Price and EMA20 are above EMA50.")
    else:
        reasons.append("Long-term trend confirmation is absent.")
    if momentum_up:
        reasons.append("20-day return is positive and RSI is in the 50-70 momentum band.")
    else:
        reasons.append("Momentum confirmation is absent or RSI is outside the preferred band.")
    if volume_ok:
        reasons.append("Latest daily volume is at least its 20-day average.")
    else:
        reasons.append("Latest daily volume is below its 20-day average.")

    if trend_up and momentum_up and volume_ok:
        signal = "BUY_CONFIRMED"
    elif exit_trend:
        signal = "EXIT_WATCH"
    elif trend_up and momentum_up:
        signal = "BUY_WATCH"
    else:
        signal = "HOLD"

    return {
        "timestamp": valid.index[-1].isoformat(),
        "signal": signal,
        "close": round(float(row["close"]), 4),
        "ema20": round(float(row["ema20"]), 4),
        "ema50": round(float(row["ema50"]), 4),
        "rsi14": round(float(row["rsi14"]), 2),
        "return20_pct": round(float(row["return20"]) * 100, 2),
        "atr14": round(float(row["atr14"]), 4),
        "relative_volume": round(float(row["relative_volume"]), 2),
        "reasons": reasons,
        "risk_note": "Research signal only; not a recommendation or an order.",
    }


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    output = {}
    for symbol in settings.symbols:
        path = settings.data_dir / f"{symbol.lower()}_{settings.historical_interval}.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing history for {symbol}: run market_data history first.")
        df = add_indicators(load_candles(path))
        output[symbol] = classify_latest(df)
        LOG.info("%s: %s", symbol, output[symbol]["signal"])
    destination = settings.data_dir / "latest_signals.json"
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))
    print(f"Saved signals to {destination}")


if __name__ == "__main__":
    main()
