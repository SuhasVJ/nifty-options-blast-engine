
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.options.state import OptionState, NiftyState


IST = ZoneInfo("Asia/Kolkata")


def main():
    start = datetime(2026, 10, 12, 9, 15, tzinfo=IST)

    option = OptionState(instrument_token=12345)
    nifty = NiftyState()

    # Not enough history at startup.
    assert not option.has_history(30)
    assert not nifty.has_history(30)

    # Add snapshots every five seconds over 60 seconds.
    for i in range(13):
        timestamp = start + timedelta(seconds=i * 5)

        option.add_snapshot(
            price=100 + i,
            volume=i * 100,
            oi=1000 + i * 10,
            timestamp=timestamp,
        )

        nifty.add_snapshot(
            price=22000 + i * 10,
            timestamp=timestamp,
        )

    assert option.has_history(5)
    assert option.has_history(30)
    assert option.has_history(60)

    assert nifty.has_history(5)
    assert nifty.has_history(30)
    assert nifty.has_history(60)

    print("Option history readiness: PASSED")
    print("NIFTY history readiness: PASSED")
    print("All history readiness tests passed.")


if __name__ == "__main__":
    main()
