"""Simple long-only swing backtest with next-open execution and conservative stop ordering."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import pandas as pd

from .config import settings
from .signals import add_indicators, load_candles


def run_backtest(frame: pd.DataFrame, fee_bps: float = 10.0, slippage_bps: float = 5.0,
                 stop_atr: float = 2.0, target_atr: float = 3.0) -> dict:
    """Test signals without look-ahead: close signal executes at next bar open.

    If a daily bar touches both stop and target, the stop is assumed to hit first.
    Costs are charged on entry and exit. This baseline does not model taxes or impact.
    """
    df = add_indicators(frame).dropna(subset=["ema20", "ema50", "rsi14", "return20", "atr14", "relative_volume"])
    if len(df) < 3:
        return {"trades": 0, "error": "Insufficient valid candles after indicator warm-up."}

    cash = 1.0
    quantity = 0.0
    entry_price = stop_price = target_price = 0.0
    entry_time = None
    trades = []
    equity = []
    cost_rate = (fee_bps + slippage_bps) / 10000.0

    # Signal is calculated using the previous completed candle, then acted on at today's open.
    for i in range(1, len(df)):
        prev = df.iloc[i - 1]
        bar = df.iloc[i]
        timestamp = df.index[i].isoformat()

        # Existing position: conservative intraday stop/target checks.
        exit_price = None
        exit_reason = None
        if quantity > 0:
            if bar["low"] <= stop_price:
                exit_price, exit_reason = stop_price, "ATR_STOP"
            elif bar["high"] >= target_price:
                exit_price, exit_reason = target_price, "ATR_TARGET"
            elif (prev["close"] < prev["ema50"] or prev["ema20"] < prev["ema50"] or prev["rsi14"] < 45):
                exit_price, exit_reason = float(bar["open"]), "SIGNAL_EXIT"

            if exit_price is not None:
                proceeds = quantity * exit_price * (1 - cost_rate)
                pnl = proceeds - (quantity * entry_price * (1 + cost_rate))
                cash = cash + proceeds
                trades.append({
                    "entry_time": entry_time, "exit_time": timestamp,
                    "entry_price": round(entry_price, 4), "exit_price": round(float(exit_price), 4),
                    "pnl_fraction_of_entry_notional": round(pnl / max(quantity * entry_price, 1e-12), 6),
                    "reason": exit_reason,
                })
                quantity = 0.0
                entry_price = stop_price = target_price = 0.0
                entry_time = None

        # Enter at today's open only if the previous completed candle had a buy signal.
        if quantity == 0:
            trend_up = prev["close"] > prev["ema50"] and prev["ema20"] > prev["ema50"]
            momentum_up = prev["return20"] > 0 and 50 <= prev["rsi14"] <= 70
            volume_ok = prev["relative_volume"] >= 1.0
            if trend_up and momentum_up and volume_ok and float(bar["open"]) > 0:
                entry_price = float(bar["open"])
                stop_price = entry_price - stop_atr * float(prev["atr14"])
                target_price = entry_price + target_atr * float(prev["atr14"])
                if stop_price <= 0:
                    stop_price = entry_price * 0.5
                quantity = cash / (entry_price * (1 + cost_rate))
                cash = 0.0
                entry_time = timestamp

        marked_equity = cash + (quantity * float(bar["close"]) if quantity > 0 else 0.0)
        equity.append({"timestamp": timestamp, "equity": marked_equity})

    # Liquidate any open position at final close for reporting only.
    if quantity > 0:
        final_bar = df.iloc[-1]
        exit_price = float(final_bar["close"])
        proceeds = quantity * exit_price * (1 - cost_rate)
        pnl = proceeds - quantity * entry_price * (1 + cost_rate)
        trades.append({
            "entry_time": entry_time, "exit_time": df.index[-1].isoformat(),
            "entry_price": round(entry_price, 4), "exit_price": round(exit_price, 4),
            "pnl_fraction_of_entry_notional": round(pnl / max(quantity * entry_price, 1e-12), 6),
            "reason": "END_OF_DATA",
        })
        cash = proceeds
        quantity = 0.0

    returns = pd.Series([point["equity"] for point in equity], dtype=float)
    if not returns.empty:
        peak = returns.cummax()
        drawdown = returns / peak - 1.0
        max_drawdown = float(drawdown.min())
        total_return = float(returns.iloc[-1] - 1.0)
    else:
        max_drawdown, total_return = 0.0, 0.0
    wins = [trade for trade in trades if trade["pnl_fraction_of_entry_notional"] > 0]
    losses = [trade for trade in trades if trade["pnl_fraction_of_entry_notional"] <= 0]
    return {
        "trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(trades), 2) if trades else 0.0,
        "average_trade_pnl_pct": round(100 * sum(t["pnl_fraction_of_entry_notional"] for t in trades) / len(trades), 3) if trades else 0.0,
        "total_return_pct_approx": round(total_return * 100, 2),
        "max_drawdown_pct_approx": round(max_drawdown * 100, 2),
        "fee_bps_per_side": fee_bps,
        "slippage_bps_per_side": slippage_bps,
        "stop_atr": stop_atr,
        "target_atr": target_atr,
        "trades_detail": trades,
        "method_note": "Baseline research only; single-position, fully-invested long-only simulation. Equity curve is close-marked and simplified; validate before relying on results.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Backtest the Seven Horses swing baseline.")
    parser.add_argument("--fee-bps", type=float, default=10.0, help="Estimated transaction cost in basis points per side.")
    parser.add_argument("--slippage-bps", type=float, default=5.0, help="Estimated slippage in basis points per side.")
    args = parser.parse_args()
    summary = {}
    for symbol in settings.symbols:
        path = settings.data_dir / f"{symbol.lower()}_{settings.historical_interval}.json"
        if not path.exists():
            raise FileNotFoundError(f"Missing history for {symbol}: run market_data history first.")
        summary[symbol] = run_backtest(load_candles(path), fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)
    output = settings.data_dir / "backtest_summary.json"
    output.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Saved backtest to {output}")


if __name__ == "__main__":
    main()
