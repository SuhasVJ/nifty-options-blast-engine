import unittest

import numpy as np
import pandas as pd

from app.commodities.natural_gas_engine import add_indicators, evaluate_latest, generate_signals


def sample_candles(n=100):
    dates = pd.date_range("2026-09-01 09:00", periods=n, freq="5min")
    close = 300 + np.arange(n) * 0.12 + np.sin(np.arange(n) / 3) * 0.2
    return pd.DataFrame({
        "date": dates,
        "open": close - 0.05,
        "high": close + 0.25,
        "low": close - 0.25,
        "close": close,
        "volume": np.full(n, 1000),
    })


class NaturalGasEngineTests(unittest.TestCase):
    def test_indicators_are_added(self):
        result = add_indicators(sample_candles())
        for column in ("ema9", "ema21", "rsi", "atr", "vwap", "volume_sma20", "resistance20", "support20"):
            self.assertIn(column, result.columns)
        self.assertGreater(len(result), 0)

    def test_insufficient_history_waits(self):
        signal = evaluate_latest(sample_candles(20), "intraday")
        self.assertEqual(signal.direction, "WAIT")
        self.assertEqual(signal.status, "INSUFFICIENT_DATA")
        self.assertIsNone(signal.entry)

    def test_timeframe_validation(self):
        with self.assertRaises(ValueError):
            evaluate_latest(sample_candles(), "daily")

    def test_historical_signals_have_no_future_rows(self):
        candles = sample_candles(60)
        signals = generate_signals(candles, "swing")
        self.assertEqual(len(signals), 60 - 35 + 1)
        self.assertTrue(set(signals["direction"]).issubset({"BUY", "SELL", "WAIT"}))
        self.assertTrue((signals["timeframe"] == "swing").all())

    def test_buy_or_sell_has_risk_levels(self):
        # Rising synthetic candles can trigger BUY only after breakout confirmation.
        candles = sample_candles(100)
        signal = evaluate_latest(candles, "intraday")
        if signal.direction in {"BUY", "SELL"}:
            self.assertIsNotNone(signal.entry)
            self.assertIsNotNone(signal.stop_loss)
            self.assertIsNotNone(signal.target_1)
            if signal.direction == "BUY":
                self.assertLess(signal.stop_loss, signal.entry)
                self.assertGreater(signal.target_1, signal.entry)
            else:
                self.assertGreater(signal.stop_loss, signal.entry)
                self.assertLess(signal.target_1, signal.entry)


if __name__ == "__main__":
    unittest.main()
