"""Experimental GOLDM option analytics and shadow scoring. No orders or trade calls."""
from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime
from math import erf, exp, isfinite, log, pi, sqrt
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
RISK_FREE_RATE = 0.065  # Modeling assumption; not calibrated for trading.
HISTORY_SECONDS = 180
FUTURE_HISTORY_SECONDS = 240
RECENT_SECONDS = 30
MIN_OBSERVATIONS = 5
MIN_RECENT_OBSERVATIONS = 3
MAX_FUTURE_TIMESTAMP_SKEW_SECONDS = 5


def _cdf(x: float) -> float:
    return 0.5 * (1.0 + erf(x / sqrt(2.0)))


def _pdf(x: float) -> float:
    return exp(-0.5 * x * x) / sqrt(2.0 * pi)


def black76_price(F: float, K: float, T: float, r: float, sigma: float, is_call: bool) -> float:
    if min(F, K, T, sigma) <= 0:
        return 0.0
    vol_t = sigma * sqrt(T)
    d1 = (log(F / K) + 0.5 * sigma * sigma * T) / vol_t
    d2 = d1 - vol_t
    disc = exp(-r * T)
    if is_call:
        return disc * (F * _cdf(d1) - K * _cdf(d2))
    return disc * (K * _cdf(-d2) - F * _cdf(-d1))


def implied_volatility(F: float, K: float, T: float, r: float, premium: float, is_call: bool):
    if not all(isfinite(v) for v in (F, K, T, r, premium)) or min(F, K, T, premium) <= 0:
        return None
    low, high = 0.005, 5.0
    low_px = black76_price(F, K, T, r, low, is_call)
    high_px = black76_price(F, K, T, r, high, is_call)
    if premium < low_px - 1e-6 or premium > high_px + 1e-6:
        return None
    for _ in range(90):
        mid = (low + high) / 2.0
        px = black76_price(F, K, T, r, mid, is_call)
        if px > premium:
            high = mid
        else:
            low = mid
    return (low + high) / 2.0


def black76_greeks(F: float, K: float, T: float, r: float, sigma: float, is_call: bool):
    if not all(isfinite(v) for v in (F, K, T, r, sigma)) or min(F, K, T, sigma) <= 0:
        return {"delta": None, "gamma": None, "vega": None}
    vol_t = sigma * sqrt(T)
    d1 = (log(F / K) + 0.5 * sigma * sigma * T) / vol_t
    disc = exp(-r * T)
    signed_delta = disc * _cdf(d1) if is_call else disc * (_cdf(d1) - 1.0)
    return {
        "delta": signed_delta,
        "gamma": disc * _pdf(d1) / (F * vol_t),
        "vega": disc * F * _pdf(d1) * sqrt(T) / 100.0,
    }


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _valid_number(value):
    try:
        return value is not None and isfinite(float(value))
    except (TypeError, ValueError):
        return False


class GoldMShadowEngine:
    """Produces experimental descriptive scores, never a buy/sell recommendation."""

    def __init__(self, risk_free_rate=RISK_FREE_RATE):
        self.risk_free_rate = risk_free_rate
        self.history = defaultdict(lambda: deque(maxlen=300))
        self.future_history = deque(maxlen=300)

    @staticmethod
    def _time_to_expiry(expiry):
        try:
            end = datetime.combine(expiry, datetime.min.time()).replace(hour=17, tzinfo=IST)
            now = datetime.now(IST)
            seconds = (end - now).total_seconds()
            return max(seconds / (365.0 * 24 * 3600), 1.0 / (365.0 * 24 * 3600))
        except (TypeError, ValueError, OverflowError):
            return None

    def on_future(self, price, ts=None):
        timestamp = float(ts if ts is not None else datetime.now(IST).timestamp())
        if _valid_number(price) and float(price) > 0 and isfinite(timestamp):
            if self.future_history and timestamp <= self.future_history[-1][0]:
                return False
            self.future_history.append((timestamp, float(price)))
            while (
                    self.future_history
                    and timestamp - self.future_history[0][0] > FUTURE_HISTORY_SECONDS
            ):
                self.future_history.popleft()
            return True
        return False

    @staticmethod
    def _result(status, **kwargs):
        base = {
            "score": None, "status": status, "delta": None, "iv_percent": None,
            "gamma": None, "vega": None, "direction": "—",
            "underlying_direction": "—", "option_alignment": "UNKNOWN",
            "components": {}, "observations": 0,
        }
        base.update(kwargs)
        return base

    def evaluate(self, token, option_type, strike, expiry, premium, oi, volume, future_price, ts=None):
        now = float(ts if ts is not None else datetime.now(IST).timestamp())
        if not isfinite(now):
            return self._result("INVALID_TIMESTAMP")
        if not all(_valid_number(v) for v in (premium, strike, future_price)):
            return self._result("WAITING_FOR_VALID_MARKET_DATA")
        premium, strike, future_price = float(premium), float(strike), float(future_price)
        if min(premium, strike, future_price) <= 0:
            return self._result("WAITING_FOR_VALID_MARKET_DATA")
        if str(option_type).upper() not in ("CE", "PE"):
            return self._result("INVALID_OPTION_TYPE")

        hist = self.history[token]
        if hist and now <= hist[-1]["ts"]:
            return self._result(
                "OUT_OF_ORDER_TICK" if now < hist[-1]["ts"] else "DUPLICATE_TIMESTAMP",
                observations=len(hist),
            )

        current = {
            "ts": now, "ltp": premium,
            "oi": float(oi) if _valid_number(oi) else None,
            "volume": float(volume) if _valid_number(volume) else None,
            "future": future_price,
        }
        if hist:
            last = hist[-1]
            same_values = all(current[k] == last[k] for k in ("ltp", "oi", "volume", "future"))
            if same_values:
                # Do not let repeated unchanged snapshots satisfy warm-up.
                return self._result("NO_NEW_DATA", observations=len(hist))

        hist.append(current)
        while hist and now - hist[0]["ts"] > HISTORY_SECONDS:
            hist.popleft()

        T = self._time_to_expiry(expiry)
        call = str(option_type).upper() == "CE"
        iv = implied_volatility(future_price, strike, T, self.risk_free_rate, premium, call) if T else None
        greeks = black76_greeks(future_price, strike, T, self.risk_free_rate, iv, call) if iv else {"delta": None, "gamma": None, "vega": None}
        recent = [x for x in hist if 0 <= now - x["ts"] <= RECENT_SECONDS]
        if len(hist) < MIN_OBSERVATIONS or len(recent) < MIN_RECENT_OBSERVATIONS:
            return self._result(
                "WARMING_UP", delta=greeks["delta"], iv_percent=iv * 100 if iv else None,
                gamma=greeks["gamma"], vega=greeks["vega"], observations=len(hist),
            )

        base = recent[0]
        premium_return = premium / base["ltp"] - 1.0 if base["ltp"] > 0 else 0.0
        future_return = future_price / base["future"] - 1.0 if base["future"] > 0 else 0.0
        oi_change = 0.0
        if current["oi"] is not None and base["oi"] not in (None, 0):
            oi_change = (current["oi"] - base["oi"]) / abs(base["oi"])
        vol_delta = 0.0
        if current["volume"] is not None and base["volume"] is not None:
            vol_delta = max(0.0, current["volume"] - base["volume"])

        momentum_component = 25 * _clamp(abs(premium_return) / 0.015)
        oi_component = 20 * _clamp(abs(oi_change) / 0.03)
        volume_component = 15 * _clamp(vol_delta / 100.0)
        delta_component = 15 * _clamp(abs(greeks["delta"] or 0.0))
        gamma_component = 10 * _clamp((greeks["gamma"] or 0.0) * future_price / 0.05)
        alignment = premium_return * (1 if call else -1)
        alignment_component = 15 * _clamp((alignment + 0.002) / 0.012)
        components = {
            "premium_momentum": round(momentum_component, 2),
            "oi_change": round(oi_component, 2),
            "volume_activity": round(volume_component, 2),
            "delta_exposure": round(delta_component, 2),
            "gamma_exposure": round(gamma_component, 2),
            "option_directional_alignment": round(alignment_component, 2),
        }
        score = round(sum(components.values()), 2)

        if abs(future_return) < 0.00015:
            underlying_direction = "NEUTRAL"
        else:
            underlying_direction = "BULLISH" if future_return > 0 else "BEARISH"

        if abs(future_return) < 0.00015 or abs(premium_return) < 0.0001:
            option_alignment = "NEUTRAL"
        else:
            expected_premium_sign = 1 if (future_return > 0) == call else -1
            option_alignment = "ALIGNED" if premium_return * expected_premium_sign > 0 else "DIVERGENT"

        return {
            "score": score,
            "status": "SHADOW_ONLY_UNCALIBRATED",
            "delta": greeks["delta"], "iv_percent": iv * 100 if iv else None,
            "gamma": greeks["gamma"], "vega": greeks["vega"],
            # Backward-compatible field; this means the underlying futures trend.
            "direction": underlying_direction,
            "underlying_direction": underlying_direction,
            "option_alignment": option_alignment,
            "components": components,
            "premium_return_30s_pct": round(premium_return * 100, 4),
            "future_return_30s_pct": round(future_return * 100, 4),
            "oi_change_pct": round(oi_change * 100, 3),
            "observations": len(hist),
        }
