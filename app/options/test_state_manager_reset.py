
from datetime import datetime
from zoneinfo import ZoneInfo

from app.options.state_manager import OptionStateManager


IST = ZoneInfo("Asia/Kolkata")


def main():
    manager = OptionStateManager()
    now = datetime.now(IST)

    # Seed option history.
    option_state = manager.update({
        "instrument_token": 12345,
        "last_price": 100.0,
        "volume_traded": 1000,
        "oi": 500,
        "exchange_timestamp": now,
    })

    assert option_state is not None
    assert len(option_state.history) == 1

    # Seed NIFTY history.
    nifty_state = manager.update_nifty({
        "instrument_token": 256265,
        "last_price": 22000.0,
        "exchange_timestamp": now,
    })

    assert nifty_state is not None
    assert len(nifty_state.history) == 1

    # Simulate reconnect recovery.
    manager.reset()

    assert len(manager.all()) == 0
    assert manager.get(12345) is None
    assert len(manager.get_nifty().history) == 0
    assert manager.get_nifty().last_price == 0.0

    assert not manager.get_nifty().has_history(30)

    print("[PASS] Option history cleared")
    print("[PASS] NIFTY history cleared")
    print("[PASS] Old option states removed")
    print("[PASS] Fresh history required after reset")
    print("\nSTATE MANAGER RESET TEST: ALL PASSED")


if __name__ == "__main__":
    main()
