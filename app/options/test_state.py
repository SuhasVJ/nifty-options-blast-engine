
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.options.state import OptionState, NiftyState


IST = ZoneInfo("Asia/Kolkata")


def main():
    start = datetime(2026, 10, 12, 9, 15, 0, tzinfo=IST)
    state = OptionState(instrument_token=12345)

    # One snapshot every 5 seconds, with cumulative volume and OI.
    for i in range(13):
        timestamp = start + timedelta(seconds=i * 5)

        state.add_snapshot(
            price=100 + i,
            volume=i * 100,
            oi=1000 + i * 10,
            timestamp=timestamp,
        )

    print("Latest price:", state.last_price)
    print("Price change 30s (%):", state.price_change_pct(30))
    print("OI change 30s:", state.oi_change(30))
    print("OI change 30s (%):", state.oi_change_pct(30))
    print("Volume change 30s:", state.volume_change(30))
    print("Volume acceleration:", state.volume_acceleration())

    # Latest price is 112; price 30 seconds earlier was 106.
    expected_price_change = ((112 - 106) / 106) * 100
    assert abs(
        state.price_change_pct(30) - expected_price_change
    ) < 1e-9

    assert state.oi_change(30) == 60
    assert state.volume_change(30) == 600
    assert abs(state.volume_acceleration() - 1.0) < 1e-9

    nifty = NiftyState()

    for i in range(13):
        nifty.add_snapshot(
            price=22000 + i * 10,
            timestamp=start + timedelta(seconds=i * 5),
        )

    assert nifty.price_change_pct(30) > 0

    # Insufficient history must not generate a false movement.
    empty_state = OptionState(instrument_token=999)
    assert empty_state.price_change_pct(30) == 0.0
    assert empty_state.oi_change_pct(30) == 0.0
    assert empty_state.volume_acceleration() == 0.0

    print("NIFTY change 30s (%):", nifty.price_change_pct(30))
    print("\nAll state tests passed.")


if __name__ == "__main__":
    main()
