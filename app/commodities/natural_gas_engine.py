"""Balanced trend/momentum signals for MCX Natural Gas futures.

Signals only: this module never places or modifies orders.
Input DataFrame columns: date, open, high, low, close, volume.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

import numpy as np
import pandas as pd

Direction = Literal["BUY", "SELL", "WAIT"]


@dataclass(frozen=True)
class Signal:
    timestamp: str
    timeframe: str
    direction: Direction
    entry: float | None
    stop_loss: float | None
    target_1: float | None
    target_2: float | None
    risk_reward_target_1: float | None
    confidence: int
    reasons: list[str]
    status: str = "CLOSED_CANDLE_SIGNAL"

    def to_dict(self) -> dict:
        return asdict(self)


def add_indicators(candles: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with EMA, RSI, ATR, VWAP and volume-average indicators."""
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(candles.columns)
    if missing:
        raise ValueError(f"Missing candle columns: {sorted(missing)}")
    df = candles.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close"]).sort_values("date")
    df = df.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    df["ema9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
    delta = df["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    df.loc[(loss == 0) & (gain > 0), "rsi"] = 100
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
        ], axis=1).max(axis=1)
    df["atr"] = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    typical = (df["high"] + df["low"] + df["close"]) / 3
    # VWAP resets by exchange-local trading date.
    trade_day = df["date"].dt.date
    pv = typical * df["volume"].fillna(0)
    df["_pv"] = pv
    df["_vol"] = df["volume"].fillna(0)
    df["vwap"] = df.groupby(trade_day)["_pv"].cumsum() / df.groupby(trade_day)["_vol"].cumsum().replace(0, np.nan)
    df["volume_sma20"] = df["volume"].rolling(20, min_periods=10).mean()
    df["resistance20"] = df["high"].shift(1).rolling(20, min_periods=10).max()
    df["support20"] = df["low"].shift(1).rolling(20, min_periods=10).min()
    return df.drop(columns=["_pv", "_vol"])


def evaluate_latest(candles: pd.DataFrame, timeframe: str = "intraday") -> Signal:
    """Evaluate only the most recent completed candle; no order execution."""
    if timeframe not in {"intraday", "swing"}:
        raise ValueError("timeframe must be 'intraday' or 'swing'")
    df = add_indicators(candles)
    if len(df) < 35:
        return Signal(str(df.iloc[-1]["date"]) if not df.empty else "", timeframe,
                      "WAIT", None, None, None, None, None, 0,
                      ["Need at least 35 completed candles"], "INSUFFICIENT_DATA")
    row = df.iloc[-1]
    previous = df.iloc[-2]
    values = [row[k] for k in ("ema9", "ema21", "rsi", "atr", "vwap", "volume_sma20", "resistance20", "support20")]
    if any(pd.isna(v) for v in values):
        return Signal(str(row["date"]), timeframe, "WAIT", None, None, None, None, None, 0,
                      ["Indicator warm-up incomplete"], "INSUFFICIENT_DATA")

    volume_ok = float(row["volume"]) >= 0.8 * float(row["volume_sma20"])
    breakout = float(row["close"]) > float(row["resistance20"])
    breakdown = float(row["close"]) < float(row["support20"])
    buy_checks = [
        float(row["close"]) > float(row["vwap"]),
        float(row["ema9"]) > float(row["ema21"]),
        float(row["rsi"]) >= 55,
        breakout,
        volume_ok,
        float(row["close"]) >= float(previous["close"]),
        ]
    sell_checks = [
        float(row["close"]) < float(row["vwap"]),
        float(row["ema9"]) < float(row["ema21"]),
        float(row["rsi"]) <= 45,
        breakdown,
        volume_ok,
        float(row["close"]) <= float(previous["close"]),
        ]
    buy_score, sell_score = sum(buy_checks), sum(sell_checks)
    # Balanced: require trend + momentum + price structure, not just indicator votes.
    direction: Direction = "WAIT"
    reasons: list[str] = []
    if buy_score >= 5 and buy_checks[0] and buy_checks[1] and buy_checks[2] and buy_checks[3] and volume_ok:
        direction = "BUY"
        reasons = ["Close above VWAP", "EMA9 above EMA21", "RSI confirms bullish momentum",
                   "20-candle resistance breakout", "Volume confirmation" if volume_ok else "Volume below confirmation threshold"]
        score = buy_score
    elif sell_score >= 5 and sell_checks[0] and sell_checks[1] and sell_checks[2] and sell_checks[3] and volume_ok:
        direction = "SELL"
        reasons = ["Close below VWAP", "EMA9 below EMA21", "RSI confirms bearish momentum",
                   "20-candle support breakdown", "Volume confirmation" if volume_ok else "Volume below confirmation threshold"]
        score = sell_score
    else:
        score = max(buy_score, sell_score)
        reasons = ["No complete trend + momentum + breakout/breakdown confirmation"]
    if direction == "WAIT":
        return Signal(str(row["date"]), timeframe, direction, None, None, None, None, None,
                      int(round(score / 6 * 100)), reasons)
    entry = float(row["close"])
    atr = float(row["atr"])
    # ATR-based levels are estimates from the signal candle, not guaranteed fills.
    risk = max(1.2 * atr, 2 * 0.05)
    if direction == "BUY":
        stop = entry - risk
        t1, t2 = entry + 1.5 * risk, entry + 2.0 * risk
    else:
        stop = entry + risk
        t1, t2 = entry - 1.5 * risk, entry - 2.0 * risk
    return Signal(str(row["date"]), timeframe, direction, round(entry, 2), round(stop, 2),
                  round(t1, 2), round(t2, 2), 1.5, int(round(score / 6 * 100)), reasons)


def generate_signals(candles: pd.DataFrame, timeframe: str = "intraday") -> pd.DataFrame:
    """Evaluate each candle using only data available through that candle."""
    df = add_indicators(candles)
    out = []
    for end in range(35, len(df) + 1):
        # Evaluate at each historical point to avoid look-ahead bias.
        sig = evaluate_latest(df.iloc[:end][["date", "open", "high", "low", "close", "volume"]], timeframe)
        out.append(sig.to_dict())
    return pd.DataFrame(out)