"""Regression tests for Seven Horses backtest accounting and input validation."""
from __future__ import annotations

import unittest
from unittest.mock import patch

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


    def test_end_of_data_exit_updates_final_equity_after_exit_costs(self):
        index = pd.date_range("2026-01-01", periods=4, freq="D")
        frame = pd.DataFrame({
            "open": [99.0, 100.0, 102.0, 103.0],
            "high": [100.0, 104.0, 104.0, 104.0],
            "low": [98.0, 99.0, 101.0, 102.0],
            "close": [99.0, 102.0, 103.0, 103.5],
            "volume": [1000.0] * 4,
            "ema20": [98.0] * 4,
            "ema50": [95.0] * 4,
            "rsi14": [60.0] * 4,
            "return20": [0.05] * 4,
            "atr14": [2.0] * 4,
            "relative_volume": [1.2] * 4,
        }, index=index)

        with patch("app.seven_horses.backtest.add_indicators", return_value=frame):
            result = run_backtest(frame)

        self.assertEqual(result["trades"], 1)
        self.assertEqual(result["trades_detail"][0]["reason"], "END_OF_DATA")
        final_equity = result["equity_curve"][-1]["equity"]
        self.assertLess(final_equity, 103.5 / 100.0)
        self.assertAlmostEqual(result["total_return_pct_approx"], round((final_equity - 1.0) * 100, 2))

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


    def test_open_position_equity_reserves_exit_costs(self):
        index = pd.date_range("2026-01-01", periods=4, freq="D")
        frame = pd.DataFrame({
            "open": [99.0, 100.0, 102.0, 103.0],
            "high": [100.0, 101.0, 103.0, 104.0],
            "low": [98.0, 99.5, 101.0, 102.0],
            "close": [99.0, 100.5, 102.5, 103.5],
            "volume": [1000.0] * 4,
            "ema20": [98.0] * 4,
            "ema50": [95.0] * 4,
            "rsi14": [60.0] * 4,
            "return20": [0.05] * 4,
            "atr14": [10.0] * 4,
            "relative_volume": [1.2] * 4,
        }, index=index)

        fee_bps = 10.0
        slippage_bps = 5.0
        cost_rate = (fee_bps + slippage_bps) / 10000.0

        with patch("app.seven_horses.backtest.add_indicators", return_value=frame):
            result = run_backtest(
                frame, fee_bps=fee_bps, slippage_bps=slippage_bps
            )

        curve = result["equity_curve"]
        # Entry occurs on the second bar; position remains open before final liquidation.
        entry_price = frame.iloc[1]["open"]
        quantity = 1.0 / (entry_price * (1.0 + cost_rate))
        expected_mark = quantity * frame.iloc[2]["close"] * (1.0 - cost_rate)

        self.assertAlmostEqual(curve[2]["equity"], expected_mark, places=8)
        self.assertEqual(result["trades_detail"][-1]["reason"], "END_OF_DATA")
        self.assertAlmostEqual(
            result["total_return_pct_approx"],
            round((curve[-1]["equity"] - 1.0) * 100, 2),
        )

    def test_end_date_is_inclusive_and_allows_holiday_gap(self):
        from datetime import date

        index = pd.to_datetime([
            "2026-10-15",
            "2026-10-16",
            "2026-10-19",
            # 2026-10-20 is a market holiday: no candle expected.
            "2026-10-21",
            "2026-10-22",
        ]).tz_localize("Asia/Kolkata")

        close = pd.Series([100., 101., 102., 103., 104.], index=index)
        frame = pd.DataFrame({
            "open": close,
            "high": close + 2,
            "low": close - 2,
            "close": close,
            "volume": 1000.,
            "ema20": 99.,
            "ema50": 98.,
            "rsi14": 60.,
            "return20": 0.05,
            "atr14": 2.,
            "relative_volume": 1.2,
        }, index=index)

        captured = {}

        def inspect_indicators(candles):
            captured["dates"] = [d.date().isoformat() for d in candles.index]
            return candles

        with patch(
            "app.seven_horses.backtest.add_indicators",
            side_effect=inspect_indicators,
        ):
            result = run_backtest(frame, end_date=date(2026, 10, 20))

        self.assertEqual(
            captured["dates"],
            ["2026-10-15", "2026-10-16", "2026-10-19"],
        )
        curve = result.get("equity_curve", [])
        self.assertTrue(curve)
        self.assertEqual(curve[-1]["timestamp"][:10], "2026-10-19")
        self.assertTrue(
            all(point["timestamp"][:10] <= "2026-10-20" for point in curve)
        )


if __name__ == "__main__":
    unittest.main()
