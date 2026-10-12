"""Experimental GOLDM dual-strategy comparison. Monitoring-only; never places orders."""
from __future__ import annotations

from math import isfinite
from typing import Any

MIN_HISTORY_POINTS = 5
MIN_HISTORY_SPAN_SECONDS = 30.0
MIN_STRATEGY_SCORE = 65.0
MIN_ABS_DELTA = 0.35
MAX_ABS_DELTA = 0.70
MAX_IV_PERCENT = 35.0
MAX_SPREAD_PERCENT = 1.50


def _finite(value: Any) -> bool:
    try:
        return value is not None and isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _return(start: float, end: float) -> float:
    return end / start - 1.0 if start > 0 else 0.0


def _direction(value: float, threshold: float) -> str:
    if value >= threshold:
        return "BULLISH"
    if value <= -threshold:
        return "BEARISH"
    return "NEUTRAL"


def _strategy_score(history: list[tuple[float, float]]) -> dict[str, Any]:
    """Score momentum and trend continuation from timestamped futures ticks.

    Tick sampling is not candle data. This prototype must be calibrated and
    validated through backtesting/forward testing before any trading use.
    """
    points = [(float(ts), float(price)) for ts, price in history
              if _finite(ts) and _finite(price) and float(price) > 0]
    points.sort(key=lambda item: item[0])
    warming = {
        "momentum": {"score": None, "direction": "NEUTRAL", "status": "WARMING_UP",
                     "reason": "Collect at least five valid futures observations spanning 30 seconds"},
        "trend": {"score": None, "direction": "NEUTRAL", "status": "WARMING_UP",
                  "reason": "Collect at least five valid futures observations spanning 30 seconds"},
    }
    if len(points) < MIN_HISTORY_POINTS:
        return warming
    latest_ts, latest = points[-1]
    points = [(ts, price) for ts, price in points if latest_ts - ts <= 240]
    if len(points) < MIN_HISTORY_POINTS or points[-1][0] - points[0][0] < MIN_HISTORY_SPAN_SECONDS:
        return warming

    def price_at_or_before(age: float) -> float | None:
        target = latest_ts - age
        found = [price for ts, price in points if ts <= target]
        return found[-1] if found else None

    p30 = price_at_or_before(30)
    p90 = price_at_or_before(90)
    p180 = price_at_or_before(180)

    if p30 is None or p90 is None or p180 is None:
        return {
            "momentum": {
                "score": None,
                "direction": "NEUTRAL",
                "status": "WARMING_UP",
                "reason": "Waiting for valid 30s and 90s reference prices",
            },
            "trend": {
                "score": None,
                "direction": "NEUTRAL",
                "status": "WARMING_UP",
                "reason": "Waiting for valid 90s and 180s reference prices",
            },
        }

    ret30 = _return(p30, latest)
    ret90 = _return(p90, latest)
    ret180 = _return(p180, latest)

    direction = _direction(ret30, 0.0005)
    momentum_confirmed = direction != "NEUTRAL" and (ret90 == 0 or (ret90 > 0) == (ret30 > 0))
    momentum_score = 100 * (
        0.55 * _clamp(abs(ret30) / 0.0020)
        + 0.30 * _clamp(abs(ret90) / 0.0040)
        + 0.15 * float(momentum_confirmed)
    )
    if not momentum_confirmed:
        momentum_score = min(momentum_score, 59.0)

    trend_direction = _direction(ret180, 0.0008)
    window = [price for ts, price in points if latest_ts - ts <= 180]
    recent_low, recent_high = min(window), max(window)
    if trend_direction == "BULLISH":
        pullback = _return(recent_high, latest)
        continuation = ret30 > 0
        pullback_ok = -0.0030 <= pullback <= -0.0001
    elif trend_direction == "BEARISH":
        pullback = _return(recent_low, latest)
        continuation = ret30 < 0
        pullback_ok = 0.0001 <= pullback <= 0.0030
    else:
        continuation, pullback_ok = False, False

    trend_confirmed = (
        trend_direction != "NEUTRAL" and continuation and pullback_ok
        and (ret90 == 0 or (ret90 > 0) == (ret180 > 0))
    )
    trend_score = 100 * (
        0.45 * _clamp(abs(ret180) / 0.0040)
        + 0.25 * _clamp(abs(ret90) / 0.0030)
        + 0.15 * float(pullback_ok)
        + 0.15 * float(continuation)
    )
    if not trend_confirmed:
        trend_score = min(trend_score, 59.0)

    return {
        "momentum": {
            "score": round(momentum_score, 2), "direction": direction,
            "status": "SETUP" if momentum_confirmed else "NO_SETUP",
            "reason": "Short-term move and 90-second direction agree" if momentum_confirmed
                      else "Waiting for directional momentum confirmation",
            "return_30s_pct": round(ret30 * 100, 4), "return_90s_pct": round(ret90 * 100, 4),
        },
        "trend": {
            "score": round(trend_score, 2), "direction": trend_direction,
            "status": "SETUP" if trend_confirmed else "NO_SETUP",
            "reason": "Trend, pullback and continuation checks agree" if trend_confirmed
                      else "Waiting for established trend and pullback-continuation confirmation",
            "return_90s_pct": round(ret90 * 100, 4), "return_180s_pct": round(ret180 * 100, 4),
        },
    }


def _option_eligible(option: dict[str, Any]) -> tuple[bool, str]:
    if not str(option.get("score_status", "")).startswith("SHADOW_ONLY_UNCALIBRATED"):
        return False, "Option analytics are not warmed up"
    if not _finite(option.get("ltp")) or float(option["ltp"]) <= 0:
        return False, "Missing/invalid option premium"
    if not _finite(option.get("delta")):
        return False, "Delta unavailable"
    if not MIN_ABS_DELTA <= abs(float(option["delta"])) <= MAX_ABS_DELTA:
        return False, f"Absolute delta must be {MIN_ABS_DELTA:.2f}–{MAX_ABS_DELTA:.2f}"
    if not _finite(option.get("iv_percent")) or float(option["iv_percent"]) > MAX_IV_PERCENT:
        return False, f"IV unavailable or above {MAX_IV_PERCENT:.0f}% research limit"
    if not _finite(option.get("spread_percent")):
        return False, "Bid/ask spread unavailable; liquidity not confirmed"
    if not 0 <= float(option["spread_percent"]) <= MAX_SPREAD_PERCENT:
        return False, f"Spread exceeds {MAX_SPREAD_PERCENT:.2f}% research limit"
    if not _finite(option.get("volume")) or float(option["volume"]) <= 0:
        return False, "Positive traded volume not confirmed"
    if not _finite(option.get("score")):
        return False, "Option shadow score unavailable"
    return True, "Passed prototype eligibility filters"


def compare_strategies(
    future_history: list[tuple[float, float]],
    options: list[dict[str, Any]],
    now_ts: float | None = None,
) -> dict[str, Any]:
    """Return independent strategy evaluations and the best eligible candidate."""
    strategies = _strategy_score(future_history)
    candidates: list[dict[str, Any]] = []

    for key, label in (("momentum", "Intraday Momentum"), ("trend", "Trend Following")):
        strategy = strategies[key]
        option_type = "CE" if strategy["direction"] == "BULLISH" else (
            "PE" if strategy["direction"] == "BEARISH" else None
        )
        rejected: list[str] = []
        best = None
        if strategy["status"] == "SETUP" and (strategy["score"] or 0) >= MIN_STRATEGY_SCORE:
            for option in options:
                if str(option.get("option_type", "")).upper() != option_type:
                    continue
                eligible, reason = _option_eligible(option)
                if not eligible:
                    rejected.append(f"{option.get('tradingsymbol', 'contract')}: {reason}")
                    continue
                combined = round(0.60 * float(strategy["score"]) + 0.40 * float(option["score"]), 2)
                candidate = {
                    "strategy": label, "strategy_key": key, "direction": strategy["direction"],
                    "score": combined, "strategy_score": strategy["score"],
                    "option_score": float(option["score"]), "tradingsymbol": option.get("tradingsymbol"),
                    "option_type": option.get("option_type"), "strike": option.get("strike"),
                    "expiry": option.get("expiry"), "ltp": option.get("ltp"),
                    "delta": option.get("delta"), "iv_percent": option.get("iv_percent"),
                    "spread_percent": option.get("spread_percent"), "status": "SHADOW_CANDIDATE",
                    "reason": strategy["reason"],
                }
                if best is None or candidate["score"] > best["score"]:
                    best = candidate
        strategy["candidate"] = best
        strategy["rejections"] = rejected[:5]
        if best:
            strategy["candidate_status"] = "SHADOW_CANDIDATE"
            candidates.append(best)
        elif strategy["status"] == "WARMING_UP":
            strategy["candidate_status"] = "WARMING_UP"
        elif strategy["status"] != "SETUP" or (strategy["score"] or 0) < MIN_STRATEGY_SCORE:
            strategy["candidate_status"] = "NO_SETUP"
        else:
            strategy["candidate_status"] = "NO_ELIGIBLE_OPTION"

    winner = max(candidates, key=lambda item: item["score"]) if candidates else None
    return {
        "mode": "MONITORING_ONLY", "calibrated": False, "threshold": MIN_STRATEGY_SCORE,
        "strategies": strategies, "best_candidate": winner,
        "status": "SHADOW_CANDIDATE" if winner else "NO_TRADE",
        "message": (
            f"Top eligible shadow candidate: {winner['strategy']} {winner['tradingsymbol']}"
            if winner else "NO TRADE — no strategy and option combination passed all prototype checks"
        ),
        "notes": [
            "Scores are experimental rankings, not probabilities of profit.",
            "A candidate requires fresh analytics, delta/IV, positive volume and a valid bid/ask spread.",
            "No orders are submitted by this module.",
        ],
    }
