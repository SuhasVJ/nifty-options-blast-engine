import unittest
from app.commodities.goldm_strategy_comparison import compare_strategies


def option(option_type="CE", spread=0.4):
    return {
        "tradingsymbol": "GOLDM_TEST", "option_type": option_type, "strike": 150000,
        "expiry": "2026-10-29", "ltp": 500.0, "volume": 100, "score": 75.0,
        "score_status": "SHADOW_ONLY_UNCALIBRATED", "delta": 0.5 if option_type == "CE" else -0.5,
        "iv_percent": 22.0, "spread_percent": spread,
    }


class GoldMDualStrategyTests(unittest.TestCase):
    def test_empty_history_returns_no_trade(self):
        result = compare_strategies([], [option()])
        self.assertEqual(result["status"], "NO_TRADE")
        self.assertIsNone(result["best_candidate"])

    def test_missing_spread_fails_closed(self):
        item = option()
        item.pop("spread_percent")
        history = [(1000 + i * 10, 150000 + i * 100) for i in range(20)]
        self.assertIsNone(compare_strategies(history, [item])["best_candidate"])

    def test_illiquid_spread_fails_closed(self):
        history = [(1000 + i * 10, 150000 + i * 100) for i in range(20)]
        self.assertIsNone(compare_strategies(history, [option(spread=3.0)])["best_candidate"])

    def test_bearish_history_does_not_choose_call(self):
        history = [(1000 + i * 10, 150000 - i * 100) for i in range(20)]
        self.assertIsNone(compare_strategies(history, [option("CE")])["best_candidate"])

    def test_result_is_monitoring_only(self):
        result = compare_strategies([], [option()])
        self.assertEqual(result["mode"], "MONITORING_ONLY")
        self.assertFalse(result["calibrated"])
        self.assertNotIn("order", result)


if __name__ == "__main__":
    unittest.main()
