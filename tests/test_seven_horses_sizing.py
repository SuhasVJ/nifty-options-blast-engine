"""Tests for explainable hybrid sizing and risk caps."""
from __future__ import annotations

import unittest

from app.seven_horses.sizing import calculate_allocations


class HybridSizingTests(unittest.TestCase):
    def test_non_buy_signals_receive_zero_allocation(self):
        signals = {
            "A": {"signal": "BUY_CONFIRMED"},
            "B": {"signal": "HOLD"},
            "C": {"signal": "EXIT_WATCH"},
        }
        result = calculate_allocations(signals, {"A": 1_000_000, "B": 2_000_000, "C": 3_000_000})
        rows = result["symbols"]
        self.assertGreater(rows["A"]["target_weight_pct"], 0)
        self.assertEqual(rows["B"]["target_weight_pct"], 0)
        self.assertEqual(rows["C"]["target_weight_pct"], 0)

    def test_caps_single_symbol_and_total_exposure(self):
        signals = {f"S{i}": {"signal": "BUY_CONFIRMED"} for i in range(7)}
        result = calculate_allocations(
            signals, {symbol: 1_000_000 for symbol in signals},
            max_weight=0.20, max_deployed=0.75,
        )
        weights = [row["target_weight_pct"] for row in result["symbols"].values()]
        self.assertLessEqual(max(weights), 20.0)
        self.assertLessEqual(sum(weights), 75.0)
        self.assertAlmostEqual(sum(weights), 75.0, places=1)

    def test_buy_watch_gets_less_signal_strength_than_confirmed(self):
        signals = {
            "A": {"signal": "BUY_CONFIRMED"},
            "B": {"signal": "BUY_WATCH"},
        }
        result = calculate_allocations(signals, {"A": 1_000_000, "B": 1_000_000})
        rows = result["symbols"]
        self.assertGreater(rows["A"]["signal_strength"], rows["B"]["signal_strength"])
        self.assertGreater(rows["A"]["target_weight_pct"], rows["B"]["target_weight_pct"])

    def test_rejects_invalid_component_weights(self):
        with self.assertRaises(ValueError):
            calculate_allocations(
                {"A": {"signal": "BUY_CONFIRMED"}}, {"A": 1_000_000},
                liquidity_weight=0.5, strategic_weight=0.5, signal_weight=0.5,
            )

    def test_no_eligible_signals_means_zero_exposure(self):
        result = calculate_allocations(
            {"A": {"signal": "HOLD"}, "B": {"signal": "INSUFFICIENT_DATA"}},
            {"A": 1_000_000, "B": 2_000_000},
        )
        self.assertEqual(result["actual_deployed_pct"], 0.0)


if __name__ == "__main__":
    unittest.main()
