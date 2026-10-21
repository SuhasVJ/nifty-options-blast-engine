"""Regression tests for Seven Horses backtest accounting and input validation."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from app.seven_horses.backtest import _close_trade, run_backtest


class BacktestTests(unittest.TestCase):
    def test_close_trade_applies_costs_and_records_reason(self):
        trades = []
        proceeds = _close_trade(
            trades,
            entry_time="2026-01-01T00:00:00",
            exit_time="2026-01-02T00:00:00",
            entry_price=100.0,
            exit_price=110.0,
            quantity=1.0,
            cost_rate=0.0015,
            reason="END_OF_DATA",
        )
        self.assertAlmostEqual(proceeds, 110.0 * (1.0 - 0.0015))
        self.assertEqual(trades[0]["reason"], "END_OF_DATA")
        self.assertGreater(trades[0]["pnl_fraction_of_entry_notional"], 0)

    def test_rejects_invalid_costs_and_risk_parameters(self):
        index = pd.date_range("2025-01-01", periods=80, freq="D")
        close = pd.Series(100 + np.arange(80) * 0.1 + np.sin(np.arange(80)), index=index)
        frame = pd.DataFrame({
            "open": close,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": 1000,
        }, index=index)
        with self.assertRaises(ValueError):
            run_backtest(frame, fee_bps=-1)
        with self.assertRaises(ValueError):
            run_backtest(frame, stop_atr=0)

    def test_short_history_returns_insufficient_data(self):
        index = pd.date_range("2026-01-01", periods=10, freq="D")
        close = pd.Series(np.arange(10, dtype=float) + 100, index=index)
        frame = pd.DataFrame({
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1000,
        }, index=index)
        result = run_backtest(frame)
        self.assertEqual(result["trades"], 0)
        self.assertIn("error", result)

    def test_return_is_consistent_with_final_equity_point(self):
        index = pd.date_range("2025-01-01", periods=100, freq="D")
        steps = np.arange(100, dtype=float)
        close = pd.Series(100 + steps * 0.15 + np.sin(steps * 1.7) * 2, index=index)
        frame = pd.DataFrame({
            "open": close.shift(1).fillna(close.iloc[0]),
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": 1000 + (steps % 5) * 100,
        }, index=index)
        result = run_backtest(frame)
        self.assertIn("equity_curve", result)
        self.assertAlmostEqual(result["equity_curve"][0]["equity"], 1.0)
        self.assertAlmostEqual(
            result["total_return_pct_approx"],
            round((result["equity_curve"][-1]["equity"] - 1.0) * 100, 2),
        )
        self.assertIn("buy_and_hold_return_pct_approx", result)


if __name__ == "__main__":
    unittest.main()
