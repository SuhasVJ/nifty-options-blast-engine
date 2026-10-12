import unittest
from datetime import date, timedelta

from app.commodities.goldm_engine import (
    GoldMShadowEngine, black76_price, implied_volatility, black76_greeks
)


class GoldMEngineTests(unittest.TestCase):
    def test_iv_round_trip(self):
        F, K, T, r, sigma = 148500.0, 148000.0, 0.03, 0.065, 0.22
        price = black76_price(F, K, T, r, sigma, True)
        found = implied_volatility(F, K, T, r, price, True)
        self.assertIsNotNone(found)
        self.assertAlmostEqual(found, sigma, places=4)

    def test_greeks_are_finite(self):
        g = black76_greeks(148500, 148000, 0.03, 0.065, 0.22, True)
        self.assertGreater(g["delta"], 0)
        self.assertGreater(g["gamma"], 0)
        self.assertGreater(g["vega"], 0)

    def test_history_requires_fresh_observations(self):
        engine = GoldMShadowEngine()
        expiry = date.today() + timedelta(days=30)
        premium = black76_price(148500, 148000, 30 / 365, 0.065, 0.22, True)
        result = None
        for i in range(4):
            result = engine.evaluate(
                token=1, option_type="CE", strike=148000, expiry=expiry,
                premium=premium + i * 0.5, oi=1000, volume=100 + i,
                future_price=148500 + i * 5, ts=1000 + i,
            )
        self.assertEqual(result["status"], "WARMING_UP")
        result = engine.evaluate(
            token=1, option_type="CE", strike=148000, expiry=expiry,
            premium=premium + 2.0, oi=1000, volume=104,
            future_price=148520, ts=1004,
        )
        self.assertEqual(result["status"], "SHADOW_ONLY_UNCALIBRATED")
        self.assertIn(result["underlying_direction"], {"BULLISH", "BEARISH", "NEUTRAL"})
        self.assertIn(result["option_alignment"], {"ALIGNED", "DIVERGENT", "NEUTRAL"})

    def test_duplicate_and_out_of_order_timestamps_rejected(self):
        engine = GoldMShadowEngine()
        expiry = date.today() + timedelta(days=30)
        args = dict(token=7, option_type="CE", strike=148000, expiry=expiry,
                    premium=3500, oi=100, volume=10, future_price=148500)
        first = engine.evaluate(**args, ts=2000)
        duplicate = engine.evaluate(**args, ts=2000)
        old = engine.evaluate(**args, ts=1999)
        self.assertEqual(first["status"], "WARMING_UP")
        self.assertEqual(duplicate["status"], "DUPLICATE_TIMESTAMP")
        self.assertEqual(old["status"], "OUT_OF_ORDER_TICK")

    def test_unchanged_snapshot_does_not_inflate_history(self):
        engine = GoldMShadowEngine()
        expiry = date.today() + timedelta(days=30)
        args = dict(token=8, option_type="PE", strike=148000, expiry=expiry,
                    premium=3500, oi=100, volume=10, future_price=148500)
        engine.evaluate(**args, ts=3000)
        second = engine.evaluate(**args, ts=3001)
        self.assertEqual(second["status"], "NO_NEW_DATA")
        self.assertEqual(second["observations"], 1)

    def test_future_history_rejects_non_monotonic_timestamps(self):
        engine = GoldMShadowEngine()
        self.assertTrue(engine.on_future(148500, ts=100))
        self.assertFalse(engine.on_future(148510, ts=100))
        self.assertFalse(engine.on_future(148520, ts=99))
        self.assertEqual(len(engine.future_history), 1)


if __name__ == "__main__":
    unittest.main()
