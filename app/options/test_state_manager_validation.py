
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.options.state_manager import OptionStateManager


IST = ZoneInfo("Asia/Kolkata")


def run_test():
    manager = OptionStateManager()
    now = datetime.now(IST)

    valid_tick = {
        "instrument_token": 12345,
        "last_price": 100.0,
        "volume_traded": 1000,
        "oi": 500,
        "exchange_timestamp": now,
    }

    state = manager.update(valid_tick)

    assert state is not None
    assert state.last_price == 100.0
    assert state.volume == 1000
    assert state.oi == 500

    print("[PASS] Valid option tick accepted")

    # Invalid quantity must not change state or history.
    original_length = len(state.history)

    for field, value in [
        ("volume_traded", -1),
        ("volume_traded", float("nan")),
        ("volume_traded", 1.5),
        ("oi", -10),
        ("oi", float("inf")),
        ("oi", "invalid"),
    ]:
        bad_tick = {
            **valid_tick,
            field: value,
            "exchange_timestamp": now + timedelta(seconds=1),
        }

        assert manager.update(bad_tick) is None
        assert len(state.history) == original_length

    print("[PASS] Invalid volume and OI rejected")

    # Missing cumulative fields preserve previous values.
    missing_fields_tick = {
        "instrument_token": 12345,
        "last_price": 101.0,
        "exchange_timestamp": now + timedelta(seconds=2),
    }

    updated_state = manager.update(missing_fields_tick)

    assert updated_state is state
    assert state.volume == 1000
    assert state.oi == 500

    print("[PASS] Missing volume/OI preserve previous values")

    # Malformed timestamps must not modify history.
    bad_timestamp_tick = {
        **valid_tick,
        "last_price": 102.0,
        "exchange_timestamp": "not-a-timestamp",
    }

    history_length = len(state.history)
    assert manager.update(bad_timestamp_tick) is None
    assert len(state.history) == history_length


    # Older ticks must not overwrite newer state.
    old_tick = {
        **valid_tick,
        "last_price": 50.0,
        "exchange_timestamp": now - timedelta(seconds=5),
    }

    assert manager.update(old_tick) is None
    assert state.last_price == 101.0

    print("[PASS] Out-of-order ticks cannot overwrite newer state")

    # Invalid NIFTY prices and timestamps must be rejected.
    assert manager.update_nifty({
        "last_price": float("inf"),
        "exchange_timestamp": now,
    }) is None

    assert manager.update_nifty({
        "last_price": 22500.0,
        "exchange_timestamp": "invalid",
    }) is None

    nifty = manager.update_nifty({
        "last_price": 22500.0,
        "exchange_timestamp": now,
    })

    assert nifty is not None
    assert nifty.last_price == 22500.0

    print("[PASS] NIFTY validation works")
    print("\nSTATE MANAGER VALIDATION: ALL PASSED")


if __name__ == "__main__":
    run_test()
