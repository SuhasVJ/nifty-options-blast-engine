
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.options.greeks_service import GreeksService
from app.options.blast_score import BlastScoreEngine


IST = ZoneInfo("Asia/Kolkata")


def test_insufficient_history():
    """No score should be produced when history is not ready."""
    engine = BlastScoreEngine()

    result = engine.calculate(
        option_type="CE",
        greeks={
            "delta": 0.50,
            "iv": 0.13,
            "gamma": 0.0015,
        },
        price_change_5s=0.10,
        price_change_30s=0.30,
        oi_change_pct_30s=0.50,
        volume_change_30s=1000,
        volume_acceleration=1.50,
        nifty_change_pct_30s=0.10,
        data_ready=False,
    )

    assert result["score"] is None
    assert result["status"] == "INSUFFICIENT_DATA"

    print("[PASS] Insufficient history blocks scoring")


def test_invalid_option_prices():
    """Invalid option prices must not produce Greeks."""
    service = GreeksService()
    expiry = datetime.now(IST).date() + timedelta(days=3)

    invalid_prices = [0, -1, -100]

    for price in invalid_prices:
        result = service.calculate(
            spot=22500,
            strike=22500,
            option_price=price,
            option_type="CE",
            expiry_date=expiry,
        )

        assert result is None, (
            f"Expected no Greeks for option price {price}"
        )

    print("[PASS] Zero and negative option prices rejected")


def test_non_finite_score_inputs():
    """NaN and infinity must not create a non-finite score."""
    engine = BlastScoreEngine()

    result = engine.calculate(
        option_type="CE",
        greeks={
            "delta": float("nan"),
            "iv": float("inf"),
            "gamma": float("-inf"),
        },
        price_change_5s=float("nan"),
        price_change_30s=float("inf"),
        oi_change_pct_30s=float("nan"),
        volume_change_30s=float("inf"),
        volume_acceleration=float("nan"),
        nifty_change_pct_30s=float("-inf"),
        data_ready=True,
    )

    assert result["score"] is None
    assert result["status"] == "FILTERED"
    assert "components" in result

    for component_score in result["components"].values():
        assert math.isfinite(component_score)

    print("[PASS] Non-finite scoring inputs handled safely")


def test_invalid_option_type():
    """Unsupported option types must be rejected."""
    engine = BlastScoreEngine()

    try:
        engine.calculate(
            option_type="XX",
            greeks={"delta": 0.50, "iv": 0.13, "gamma": 0.0015},
            price_change_5s=0.10,
            price_change_30s=0.30,
            oi_change_pct_30s=0.50,
            volume_change_30s=1000,
            volume_acceleration=1.50,
            nifty_change_pct_30s=0.10,
            data_ready=True,
        )
    except ValueError:
        print("[PASS] Invalid option type rejected")
        return

    raise AssertionError("Invalid option type was not rejected")


def main():
    print("\n" + "=" * 60)
    print("NIFTY OPTIONS BLAST ENGINE - DATA SAFETY TESTS")
    print("=" * 60)

    test_insufficient_history()
    test_invalid_option_prices()
    test_non_finite_score_inputs()
    test_invalid_option_type()

    print("\n" + "=" * 60)
    print("DATA SAFETY TESTS: ALL PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
