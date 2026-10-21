import unittest

import numpy as np
import pandas as pd

from app.commodities.natural_gas_backtest import run_backtest


def candles(n=120):
    dates = pd.date_range("2026-09-01 09:00", periods=n, freq="5min")
    close = 300 + np.arange(n) * 0.1 + np.sin(np.arange(n) / 3) * 0.15
    return pd.DataFrame({
        "date": dates, "open": close - 0.03, "high": close + 0.2,
        "low": close - 0.2, "close": close, "volume": np.full(n, 1000),
    })


class NaturalGasBacktestTests(unittest.TestCase):
    def test_empty_signal_set_returns_metrics(self):
        frame = candles(25)
        result = run_backtest(frame, "intraday")
        self.assertEqual(result.trade_count, 0)
        self.assertEqual(result.win_rate_percent, 0)
        self.assertEqual(result.trades, [])

    def test_rejects_invalid_timeframe(self):
        with self.assertRaises(ValueError):
            run_backtest(candles(), "daily")

    def test_costs_and_slippage_must_be_nonnegative(self):
        with self.assertRaises(ValueError):
            run_backtest(candles(), slippage_points=-0.1)

    def test_trade_metrics_are_consistent(self):
        result = run_backtest(candles(), "swing", slippage_points=0.02, cost_points_per_side=0.01)
        self.assertEqual(result.trade_count, len(result.trades))
        self.assertGreaterEqual(result.max_drawdown_r, 0)
        self.assertIn("next candle open", result.assumptions[0])


if __name__ == "__main__":
    unittest.main()
