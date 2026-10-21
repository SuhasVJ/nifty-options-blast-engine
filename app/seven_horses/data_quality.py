"""Audit Seven Horses historical OHLCV files without modifying source data.

The exchange calendar is a version-controlled snapshot of NSE Capital Market
(Equities) full-day closures. Special Muhurat trading sessions are not treated as
full-day closures. Corporate-action adjustment is outside this audit's scope.
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from .config import settings

REQUIRED_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")
HOLIDAY_CALENDAR_PATH = Path(__file__).with_name("nse_equity_holidays.json")
HOLIDAY_CALENDAR = json.loads(HOLIDAY_CALENDAR_PATH.read_text(encoding="utf-8"))
NSE_EQUITY_HOLIDAYS = {
    date.fromisoformat(item["date"]): item["description"]
    for item in HOLIDAY_CALENDAR["holidays"]
}
CALENDAR_METADATA = {
    "exchange": HOLIDAY_CALENDAR["exchange"],
    "segment": HOLIDAY_CALENDAR["segment"],
    "coverage": HOLIDAY_CALENDAR["coverage"],
    "source_urls": HOLIDAY_CALENDAR["source_urls"],
}


def audit_candles(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Return data-quality findings for raw candle records; never mutates records."""
    issues: list[dict[str, Any]] = []
    if not records:
        return {
            "status": "FAIL", "rows": 0, "valid_rows": 0, "issues": [
                {"code": "EMPTY_FILE", "severity": "ERROR", "count": 1,
                 "message": "No candle records were provided."}
            ],
            "date_range": None, "potential_missing_business_days": [],
            "holiday_calendar": CALENDAR_METADATA,
        }

    missing_fields = sum(
        1 for row in records
        if any(field not in row or row.get(field) is None for field in REQUIRED_FIELDS)
    )
    if missing_fields:
        issues.append({
            "code": "MISSING_FIELDS", "severity": "ERROR", "count": missing_fields,
            "message": "One or more rows lack a required OHLCV field.",
        })

    frame = pd.DataFrame(records)
    for col in ("open", "high", "low", "close", "volume"):
        if col not in frame:
            frame[col] = float("nan")
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    if "timestamp" not in frame:
        frame["timestamp"] = pd.NaT
    frame["timestamp"] = (
        pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
        .dt.tz_convert("Asia/Kolkata")
    )

    bad_timestamp = int(frame["timestamp"].isna().sum())
    if bad_timestamp:
        issues.append({
            "code": "INVALID_TIMESTAMP", "severity": "ERROR", "count": bad_timestamp,
            "message": "Rows with missing or unparseable timestamps cannot be audited by date.",
        })

    numeric_cols = ["open", "high", "low", "close", "volume"]
    invalid_numeric = int(frame[numeric_cols].isna().any(axis=1).sum())
    if invalid_numeric:
        issues.append({
            "code": "INVALID_NUMERIC", "severity": "ERROR", "count": invalid_numeric,
            "message": "Rows contain missing or non-numeric OHLCV values.",
        })

    numeric_valid = frame[numeric_cols].notna().all(axis=1)
    price_valid = (frame[["open", "high", "low", "close"]] > 0).all(axis=1)
    if int((numeric_valid & ~price_valid).sum()):
        issues.append({
            "code": "NON_POSITIVE_PRICE", "severity": "ERROR",
            "count": int((numeric_valid & ~price_valid).sum()),
            "message": "OHLC prices must all be greater than zero.",
        })

    if int((numeric_valid & (frame["volume"] < 0)).sum()):
        issues.append({
            "code": "NEGATIVE_VOLUME", "severity": "ERROR",
            "count": int((numeric_valid & (frame["volume"] < 0)).sum()),
            "message": "Volume cannot be negative.",
        })

    ohlc_valid = (
        (frame["high"] >= frame[["open", "close", "low"]].max(axis=1))
        & (frame["low"] <= frame[["open", "close", "high"]].min(axis=1))
    )
    bad_ohlc = numeric_valid & ~ohlc_valid
    if int(bad_ohlc.sum()):
        issues.append({
            "code": "INCONSISTENT_OHLC", "severity": "ERROR",
            "count": int(bad_ohlc.sum()),
            "message": "High must be at least open, close, and low; low must be at most open, close, and high.",
        })

    valid_timestamps = frame["timestamp"].dropna()
    duplicate_count = int(valid_timestamps.duplicated(keep=False).sum())
    if duplicate_count:
        issues.append({
            "code": "DUPLICATE_TIMESTAMPS", "severity": "ERROR", "count": duplicate_count,
            "message": "Multiple records share the same timestamp; source rows are preserved.",
        })

    if len(valid_timestamps) > 1 and not valid_timestamps.is_monotonic_increasing:
        issues.append({
            "code": "UNSORTED_TIMESTAMPS", "severity": "WARNING", "count": 1,
            "message": "Records are not in ascending timestamp order.",
        })

    unique_dates = sorted(set(valid_timestamps.dt.date))
    observed_holidays = sorted(day for day in set(unique_dates) if day in NSE_EQUITY_HOLIDAYS)
    if observed_holidays:
        dates_text = ", ".join(day.isoformat() for day in observed_holidays)
        issues.append({
            "code": "CANDLES_ON_EXCHANGE_HOLIDAY", "severity": "ERROR",
            "count": len(observed_holidays),
            "message": (
                "Candles fall on dates listed as full-day NSE equity-market closures: "
                f"{dates_text}. Verify source timestamps and the holiday calendar."
            ),
        })

    potential_gaps: list[str] = []
    if len(unique_dates) >= 2:
        expected = {
            day.date()
            for day in pd.bdate_range(
                start=unique_dates[0],
                end=unique_dates[-1],
            )
        }
        observed = set(unique_dates)
        known_holidays = {
            day for day in NSE_EQUITY_HOLIDAYS
            if unique_dates[0] <= day <= unique_dates[-1]
        }
        potential_gaps = [
            day.isoformat()
            for day in sorted(expected - observed - known_holidays)
        ]

        if potential_gaps:
            issues.append({
                "code": "POTENTIAL_MISSING_SESSIONS", "severity": "WARNING",
                "count": len(potential_gaps),
                "message": (
                    "Weekdays without candles after excluding weekends and the versioned "
                    "NSE equity holiday calendar; verify against official circulars."
                ),
            })

    errors = sum(issue["severity"] == "ERROR" for issue in issues)
    warnings = sum(issue["severity"] == "WARNING" for issue in issues)
    unique_timestamp_rows = ~frame["timestamp"].duplicated(keep=False)
    valid_rows_mask = (
        frame["timestamp"].notna()
        & numeric_valid
        & price_valid
        & (frame["volume"] >= 0)
        & ohlc_valid
        & unique_timestamp_rows
    )
    valid_rows = int(valid_rows_mask.sum())
    return {
        "status": "FAIL" if errors else ("WARN" if warnings else "PASS"),
        "rows": len(records),
        "valid_rows": max(0, valid_rows),
        "date_range": (
            {"start": min(unique_dates).isoformat(), "end": max(unique_dates).isoformat()}
            if unique_dates else None
        ),
        "potential_missing_business_days": potential_gaps,
        "issues": issues,
        "holiday_calendar": CALENDAR_METADATA,
        "corporate_actions": {
            "status": "NOT_CHECKED",
            "note": "This audit cannot verify split/bonus adjustments or total-return treatment. Check corporate actions and price-adjustment policy separately.",
        },
    }


def audit_file(path: Path) -> dict[str, Any]:
    """Read and audit one JSON candle file."""
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "status": "FAIL", "rows": 0, "valid_rows": 0, "date_range": None,
            "potential_missing_business_days": [],
            "issues": [{"code": "FILE_READ_ERROR", "severity": "ERROR", "count": 1,
                        "message": str(exc)}],
            "corporate_actions": {"status": "NOT_CHECKED"},
        }
    if not isinstance(records, list):
        return {
            "status": "FAIL", "rows": 0, "valid_rows": 0, "date_range": None,
            "potential_missing_business_days": [],
            "issues": [{"code": "INVALID_FILE_SHAPE", "severity": "ERROR", "count": 1,
                        "message": "Expected a JSON array of candle objects."}],
            "corporate_actions": {"status": "NOT_CHECKED"},
        }
    return audit_candles(records)


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Seven Horses historical OHLCV data.")
    parser.add_argument("--data-dir", type=Path, default=settings.data_dir)
    args = parser.parse_args()
    report: dict[str, Any] = {}
    for symbol in settings.symbols:
        path = args.data_dir / f"{symbol.lower()}_{settings.historical_interval}.json"
        report[symbol] = audit_file(path) if path.exists() else {
            "status": "FAIL", "rows": 0, "valid_rows": 0, "date_range": None,
            "potential_missing_business_days": [],
            "issues": [{"code": "FILE_MISSING", "severity": "ERROR", "count": 1,
                        "message": f"Missing candle file: {path}"}],
            "corporate_actions": {"status": "NOT_CHECKED"},
        }
    destination = args.data_dir / "data_quality_report.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for symbol, result in report.items():
        issue_counts = ", ".join(f"{item['code']}={item['count']}" for item in result["issues"]) or "no issues"
        print(f"{symbol}: {result['status']} rows={result['rows']} valid_rows={result['valid_rows']} | {issue_counts}")
    print(f"Saved data-quality report to {destination}")
    if any(result["status"] == "FAIL" for result in report.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
