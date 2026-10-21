"""Simple long-only swing backtest with next-open execution and conservative stop ordering."""
from __future__ import annotations

import argparse
import json
import pandas as pd

from .config import settings
from .signals import add_indicators, load_candles


def run_backtest(frame: pd.DataFrame, fee_bps: float = 10.0, slippage_bps: float = 5.0,
                 stop_atr: float = 2.0, target_atr: float = 3.0) -> dict:
    """Test close-derived signals at the next open; no same-bar look-ahead.

    If stop and target are both touched in one daily candle, assume stop first.
    Costs are charged on each entry and exit. This baseline omits taxes and impact.
    """
    df = add_indicators(frame).dropna(subset=["ema20", "ema50", "rsi14", "return20", "atr14", "relative_volume"])
    if len(df) < 3:
        return {"trades": 0, "error": "Insufficient valid candles after indicator warm-up."}

    cash = 1.0  # normalized starting equity
    quantity = 0.0
    entry_price = stop_price = target_price = 0.0
    entry_time = None
    trades = []
    equity = []
    cost_rate = (fee_bps + slippage_bps) / 10000.0

    for i in range(1, len(df)):
        prev = df.iloc[i - 1]  # latest completed bar available before today's open
        bar = df.iloc[i]
        timestamp = df.index[i].isoformat()
        exited_today = False

        exit_price = None
        exit_reason = None
        if quantity > 0:
            # Exit signals known at yesterday's close execute at today's open.
            if prev["close"] < prev["ema50"] or prev["ema20"] < prev["ema50"] or prev["rsi14"] < 45:
                exit_price, exit_reason = float(bar["open"]), "SIGNAL_EXIT"
            else:
                # Daily OHLC cannot reveal stop/target order; assume stop wins if both touched.
                if float(bar["open"]) <= stop_price or float(bar["low"]) <= stop_price:
                    exit_price = min(float(bar["open"]), stop_price) if float(bar["open"]) < stop_price else stop_price
                    exit_reason = "ATR_STOP"
                elif float(bar["open"]) >= target_price or float(bar["high"]) >= target_price:
                    exit_price = max(float(bar["open"]), target_price) if float(bar["open"]) > target_price else target_price
                    exit_reason = "ATR_TARGET"

            if exit_price is not None:
                proceeds = quantity * exit_price * (1 - cost_rate)
                pnl = proceeds - quantity * entry_price * (1 + cost_rate)
                cash += proceeds
                trades.append({
                    "entry_time": entry_time, "exit_time": timestamp,
                    "entry_price": round(entry_price, 4), "exit_price": round(float(exit_price), 4),
                    "pnl_fraction_of_entry_notional": round(pnl / max(quantity * entry_price, 1e-12), 6),
                    "reason": exit_reason,
                })
                quantity = 0.0
                entry_price = stop_price = target_price = 0.0
                entry_time = None
                exited_today = True

        # A position exited during today's bar cannot be re-opened retroactively at today's open.
        if quantity == 0 and not exited_today:
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

                # Include entry-day stop/target checks; stop takes priority if both are touched.
                if float(bar["open"]) <= stop_price or float(bar["low"]) <= stop_price:
                    exit_price = min(float(bar["open"]), stop_price) if float(bar["open"]) < stop_price else stop_price
                    exit_reason = "ATR_STOP"
                elif float(bar["open"]) >= target_price or float(bar["high"]) >= target_price:
                    exit_price = max(float(bar["open"]), target_price) if float(bar["open"]) > target_price else target_price
                    exit_reason = "ATR_TARGET"
                else:
                    exit_price = None
                if exit_price is not None:
                    proceeds = quantity * exit_price * (1 - cost_rate)
                    pnl = proceeds - quantity * entry_price * (1 + cost_rate)
                    trades.append({
                        "entry_time": entry_time, "exit_time": timestamp,
                        "entry_price": round(entry_price, 4), "exit_price": round(float(exit_price), 4),
                        "pnl_fraction_of_entry_notional": round(pnl / max(quantity * entry_price, 1e-12), 6),
                        "reason": exit_reason,
                    })
                    cash = proceeds
                    quantity = 0.0
                    entry_price = stop_price = target_price = 0.0
                    entry_time = None

        equity.append({"timestamp": timestamp, "equity": cash + quantity * float(bar["close"])})

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

    values = pd.Series([point["equity"] for point in equity], dtype=float)
    if not values.empty:
        max_drawdown = float((values / values.cummax() - 1.0).min())
        total_return = float(values.iloc[-1] - 1.0)
    else:
        max_drawdown, total_return = 0.0, 0.0
    wins = [trade for trade in trades if trade["pnl_fraction_of_entry_notional"] > 0]
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
        "method_note": "Baseline research only; single-position, fully-invested long-only simulation. Daily OHLC stop ordering is conservative, but the simplified model requires further validation.",
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
