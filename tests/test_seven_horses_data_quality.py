"""Tests for non-destructive historical OHLCV auditing."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.seven_horses.data_quality import audit_candles, audit_file


def candle(day: str, *, open_: float = 100, high: float = 105, low: float = 95,
           close: float = 102, volume: int = 1000) -> dict:
    return {
        "timestamp": f"{day}T00:00:00+05:30",
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    }


class DataQualityTests(unittest.TestCase):
    def test_clean_consecutive_weekdays_pass(self):
        result = audit_candles([
            candle("2026-10-19"), candle("2026-10-20"), candle("2026-10-21")
        ])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["rows"], 3)
        self.assertEqual(result["potential_missing_business_days"], [])
        self.assertEqual(result["corporate_actions"]["status"], "NOT_CHECKED")

    def test_duplicate_timestamp_is_error_and_rows_are_not_mutated(self):
        records = [candle("2026-10-19"), candle("2026-10-19")]
        before = json.dumps(records, sort_keys=True)
        result = audit_candles(records)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(i["code"] == "DUPLICATE_TIMESTAMPS" for i in result["issues"]))
        self.assertEqual(json.dumps(records, sort_keys=True), before)

    def test_invalid_ohlc_and_negative_volume_are_errors(self):
        result = audit_candles([
            candle("2026-10-19", open_=110, high=105, low=95, close=102, volume=-1)
        ])
        codes = {item["code"] for item in result["issues"]}
        self.assertIn("INCONSISTENT_OHLC", codes)
        self.assertIn("NEGATIVE_VOLUME", codes)
        self.assertEqual(result["status"], "FAIL")

    def test_weekday_gap_is_warning_not_assumed_exchange_holiday(self):
        result = audit_candles([candle("2026-10-19"), candle("2026-10-21")])
        self.assertEqual(result["status"], "WARN")
        self.assertIn("2026-10-20", result["potential_missing_business_days"])

    def test_empty_and_bad_file_shapes_fail(self):
        self.assertEqual(audit_candles([])["status"], "FAIL")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candles.json"
            path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
            self.assertEqual(audit_file(path)["status"], "FAIL")

    def test_invalid_timestamp_is_reported(self):
        row = candle("2026-10-19")
        row["timestamp"] = "not-a-date"
        result = audit_candles([row])
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(i["code"] == "INVALID_TIMESTAMP" for i in result["issues"]))


if __name__ == "__main__":
    unittest.main()
