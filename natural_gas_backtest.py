"""CLI for running the Natural Gas strategy backtest against exported OHLCV CSV data."""
import argparse
import json
from pathlib import Path

import pandas as pd

from app.commodities.natural_gas_backtest import run_backtest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, help="CSV with date,open,high,low,close,volume columns")
    parser.add_argument("--timeframe", choices=("intraday", "swing"), default="intraday")
    parser.add_argument("--slippage-points", type=float, default=0.05)
    parser.add_argument("--cost-points-per-side", type=float, default=0.0,
                        help="Configure using estimated all-in per-unit charges converted to price points")
    parser.add_argument("--max-holding-bars", type=int, default=48)
    parser.add_argument("--output", default="reports/natural_gas_backtest.json")
    args = parser.parse_args()

    source = Path(args.csv)
    if not source.is_file():
        parser.error(f"CSV file not found: {source}")
    candles = pd.read_csv(source)
    result = run_backtest(
        candles,
        timeframe=args.timeframe,
        slippage_points=args.slippage_points,
        cost_points_per_side=args.cost_points_per_side,
        max_holding_bars=args.max_holding_bars,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result.to_dict(), indent=2, allow_nan=False), encoding="utf-8")
    print(f"Timeframe: {result.timeframe}")
    print(f"Trades: {result.trade_count}")
    print(f"Win rate: {result.win_rate_percent:.2f}%")
    print(f"Expectancy: {result.expectancy_r:.4f} R")
    print(f"Profit factor: {result.profit_factor if result.profit_factor is not None else 'N/A'}")
    print(f"Maximum drawdown: {result.max_drawdown_r:.4f} R")
    print(f"Net result: {result.net_r:.4f} R")
    print(f"Report: {output.resolve()}")


if __name__ == "__main__":
    main()
