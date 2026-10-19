"""Historical, next-bar-entry backtest for the MCX Natural Gas strategy.

This module never connects to Kite and never places orders. It expects OHLCV candles
exported from an authorized data source. Results are research estimates, not forecasts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from app.commodities.natural_gas_engine import evaluate_latest


@dataclass
class BacktestResult:
    timeframe: str
    trades: list[dict]
    trade_count: int
    win_rate_percent: float
    expectancy_r: float
    profit_factor: float | None
    max_drawdown_r: float
    net_r: float
    assumptions: list[str]

    def to_dict(self):
        return asdict(self)


def run_backtest(
    candles: pd.DataFrame,
    timeframe: str = "intraday",
    slippage_points: float = 0.05,
    cost_points_per_side: float = 0.0,
    max_holding_bars: int = 48,
) -> BacktestResult:
    """Simulate signals with next-bar-open entry and conservative intrabar exits.

    If a candle touches both stop and target, stop is assumed first. Target 1 is used
    as the take-profit for the initial baseline. Fees/slippage are expressed in the
    instrument's price points per unit and must be calibrated to actual contract costs.
    """
    if timeframe not in {"intraday", "swing"}:
        raise ValueError("timeframe must be 'intraday' or 'swing'")
    if slippage_points < 0 or cost_points_per_side < 0 or max_holding_bars < 1:
        raise ValueError("Costs/slippage must be non-negative and holding bars positive")
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(candles.columns)
    if missing:
        raise ValueError(f"Missing candle columns: {sorted(missing)}")
    df = candles.copy().sort_values("date").reset_index(drop=True)
    trades = []
    equity_r = 0.0
    peak_r = 0.0
    max_drawdown = 0.0
    i = 35
    while i < len(df) - 1:
        signal = evaluate_latest(df.iloc[:i + 1], timeframe).to_dict()
        direction = signal.get("direction")
        if direction not in {"BUY", "SELL"} or signal.get("stop_loss") is None or signal.get("target_1") is None:
            i += 1
            continue

        next_bar = df.iloc[i + 1]
        side = 1 if direction == "BUY" else -1
        # Penalize entry in the unfavorable direction; include round-trip costs in P&L.
        entry = float(next_bar["open"]) + side * slippage_points
        signal_entry = float(signal["entry"])
        stop_distance = abs(signal_entry - float(signal["stop_loss"]))
        if stop_distance <= 0:
            i += 1
            continue
        stop = entry - side * stop_distance
        target = entry + side * (1.5 * stop_distance)
        risk_points = stop_distance
        exit_price = None
        exit_reason = "TIME_EXIT"
        exit_idx = min(len(df) - 1, i + max_holding_bars)
        for j in range(i + 1, exit_idx + 1):
            bar = df.iloc[j]
            if side == 1:
                stop_hit = float(bar["low"]) <= stop
                target_hit = float(bar["high"]) >= target
            else:
                stop_hit = float(bar["high"]) >= stop
                target_hit = float(bar["low"]) <= target
            if stop_hit:
                exit_price, exit_reason, exit_idx = stop, "STOP_LOSS", j
                break
            if target_hit:
                exit_price, exit_reason, exit_idx = target, "TARGET_1", j
                break
        if exit_price is None:
            exit_price = float(df.iloc[exit_idx]["close"])
        gross_points = side * (exit_price - entry)
        net_points = gross_points - (2 * cost_points_per_side) - slippage_points
        r_multiple = net_points / risk_points
        trade = {
            "timeframe": timeframe,
            "direction": direction,
            "signal_time": str(signal.get("timestamp")),
            "entry_time": str(next_bar["date"]),
            "exit_time": str(df.iloc[exit_idx]["date"]),
            "entry": round(entry, 4),
            "stop_loss": round(stop, 4),
            "target_1": round(target, 4),
            "exit": round(exit_price, 4),
            "exit_reason": exit_reason,
            "gross_points": round(gross_points, 4),
            "net_points_after_configured_costs": round(net_points, 4),
            "r_multiple": round(r_multiple, 4),
        }
        trades.append(trade)
        equity_r += r_multiple
        peak_r = max(peak_r, equity_r)
        max_drawdown = max(max_drawdown, peak_r - equity_r)
        i = exit_idx + 1

    wins = [t["r_multiple"] for t in trades if t["r_multiple"] > 0]
    losses = [t["r_multiple"] for t in trades if t["r_multiple"] < 0]
    gross_wins, gross_losses = sum(wins), abs(sum(losses))
    return BacktestResult(
        timeframe=timeframe,
        trades=trades,
        trade_count=len(trades),
        win_rate_percent=round(100 * len(wins) / len(trades), 2) if trades else 0.0,
        expectancy_r=round(sum(t["r_multiple"] for t in trades) / len(trades), 4) if trades else 0.0,
        profit_factor=round(gross_wins / gross_losses, 4) if gross_losses else (None if not gross_wins else float("inf")),
        max_drawdown_r=round(max_drawdown, 4),
        net_r=round(sum(t["r_multiple"] for t in trades), 4),
        assumptions=[
            "Signals use candles available through the signal candle only; entry occurs at next candle open.",
            "Conservative ordering: if stop and target are both touched in one candle, stop is assumed first.",
            "Baseline exits at target 1, stop-loss, or max holding bars; no partial exits.",
            "Slippage and transaction costs are configurable price points per unit and require calibration.",
            "No guarantee of fills, liquidity, profitability, or future performance.",
        ],
    )
