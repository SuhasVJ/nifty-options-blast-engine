"""Explainable hybrid position sizing for Seven Horses; signals-only, never places orders."""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from .config import settings
from .signals import load_candles

LOG = logging.getLogger("seven_horses.sizing")

SIGNAL_STRENGTH = {
    "BUY_CONFIRMED": 1.0,
    "BUY_WATCH": 0.65,
    "HOLD": 0.0,
    "EXIT_WATCH": 0.0,
    "INSUFFICIENT_DATA": 0.0,
}
ELIGIBLE_SIGNALS = {"BUY_CONFIRMED", "BUY_WATCH"}


def _normalise(values: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, value) for value in values.values())
    if total <= 0:
        return {key: 0.0 for key in values}
    return {key: max(0.0, value) / total for key, value in values.items()}


def _capped_allocate(scores: dict[str, float], total_exposure: float, max_weight: float) -> dict[str, float]:
    """Allocate exposure proportionally while enforcing a per-symbol cap."""
    allocations = {symbol: 0.0 for symbol in scores}
    active = {symbol: score for symbol, score in scores.items() if score > 0}
    remaining = total_exposure
    while active and remaining > 1e-12:
        weights = _normalise(active)
        capped = [
            symbol for symbol, weight in weights.items()
            if allocations[symbol] + remaining * weight > max_weight + 1e-12
        ]
        if not capped:
            for symbol, weight in weights.items():
                allocations[symbol] += remaining * weight
            remaining = 0.0
            break
        for symbol in capped:
            room = max(0.0, max_weight - allocations[symbol])
            allocations[symbol] += room
            remaining -= room
            active.pop(symbol, None)
        if not capped:
            break
    return allocations


def calculate_allocations(
    signals: dict[str, dict[str, Any]],
    liquidity: dict[str, float],
    *,
    strategic_weights: dict[str, float] | None = None,
    max_weight: float = 0.25,
    max_deployed: float = 0.80,
    liquidity_weight: float = 0.30,
    strategic_weight: float = 0.25,
    signal_weight: float = 0.45,
) -> dict[str, Any]:
    """Return target weights based on liquidity, strategic weight and signal strength.

    Strategic weights are relative preferences, not predictions. Defaults are equal.
    Allocation is capped per symbol and at the portfolio's maximum deployed exposure.
    """
    if not 0 < max_weight <= 1:
        raise ValueError("max_weight must be in (0, 1].")
    if not 0 <= max_deployed <= 1:
        raise ValueError("max_deployed must be in [0, 1].")
    weights_sum = liquidity_weight + strategic_weight + signal_weight
    if any(weight < 0 for weight in (liquidity_weight, strategic_weight, signal_weight)) or not math.isclose(weights_sum, 1.0, abs_tol=1e-9):
        raise ValueError("Hybrid component weights must be non-negative and sum to 1.")
    symbols = list(signals)
    strategic_weights = strategic_weights or {symbol: 1.0 for symbol in symbols}
    if any(value < 0 for value in strategic_weights.values()):
        raise ValueError("Strategic weights must be non-negative.")

    # Log compression reduces domination by the most heavily traded stock.
    log_liquidity = {symbol: math.log1p(max(0.0, float(liquidity.get(symbol, 0.0)))) for symbol in symbols}
    max_liquidity = max(log_liquidity.values(), default=0.0)
    liquidity_scores = {
        symbol: (value / max_liquidity if max_liquidity > 0 else 0.0)
        for symbol, value in log_liquidity.items()
    }
    strategic_scores = _normalise({symbol: float(strategic_weights.get(symbol, 0.0)) for symbol in symbols})
    signal_scores = {symbol: SIGNAL_STRENGTH.get(str(signals[symbol].get("signal", "INSUFFICIENT_DATA")), 0.0) for symbol in symbols}

    composite = {}
    for symbol in symbols:
        if signals[symbol].get("signal") not in ELIGIBLE_SIGNALS:
            composite[symbol] = 0.0
        else:
            composite[symbol] = (
                liquidity_weight * liquidity_scores[symbol]
                + strategic_weight * strategic_scores[symbol]
                + signal_weight * signal_scores[symbol]
            )

    # Re-normalise the eligible composite scores to the desired exposure, then cap names.
    allocations = _capped_allocate(composite, max_deployed, max_weight)
    rows = {}
    for symbol in symbols:
        rows[symbol] = {
            "signal": signals[symbol].get("signal", "INSUFFICIENT_DATA"),
            "liquidity_score": round(liquidity_scores[symbol], 4),
            "strategic_score": round(strategic_scores[symbol], 4),
            "signal_strength": signal_scores[symbol],
            "composite_score": round(composite[symbol], 4),
            "target_weight_pct": round(allocations[symbol] * 100, 2),
            "estimated_traded_value_20d": round(max(0.0, float(liquidity.get(symbol, 0.0))), 2),
        }
    return {
        "mode": "hybrid",
        "signals_only": True,
        "max_deployed_pct": round(max_deployed * 100, 2),
        "max_symbol_weight_pct": round(max_weight * 100, 2),
        "actual_deployed_pct": round(sum(allocations.values()) * 100, 2),
        "component_weights": {
            "liquidity": liquidity_weight,
            "strategic_weightage": strategic_weight,
            "signal_strength": signal_weight,
        },
        "symbols": rows,
        "risk_note": "Research target weights only; not orders or personalised investment advice. Review risk and liquidity before any manual trade.",
    }


def load_liquidity_20d(data_dir: Path, symbols: tuple[str, ...]) -> dict[str, float]:
    """Estimate average daily traded value (close × volume) from the latest 20 candles."""
    values: dict[str, float] = {}
    for symbol in symbols:
        path = data_dir / f"{symbol.lower()}_{settings.historical_interval}.json"
        if not path.exists():
            LOG.warning("Missing candles for %s; assigning zero liquidity score.", symbol)
            values[symbol] = 0.0
            continue
        frame = load_candles(path).tail(20)
        if frame.empty:
            values[symbol] = 0.0
        else:
            values[symbol] = float((frame["close"] * frame["volume"]).mean())
    return values


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal_path = settings.data_dir / "latest_signals.json"
    if not signal_path.exists():
        raise FileNotFoundError("Missing latest_signals.json; run python -m app.seven_horses.signals first.")
    signals = json.loads(signal_path.read_text(encoding="utf-8"))
    liquidity = load_liquidity_20d(settings.data_dir, settings.symbols)
    result = calculate_allocations(signals, liquidity)
    destination = settings.data_dir / "latest_allocations.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"Saved target allocations to {destination}")


if __name__ == "__main__":
    main()
