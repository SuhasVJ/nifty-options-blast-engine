
from unittest.mock import Mock, patch

from app.options import live_chain


def run_test():
    # An invalid NIFTY price must not update the spot price
    # or invoke the option-chain subscription logic.
    invalid_nifty_tick = {
        "instrument_token": live_chain.NIFTY_50_TOKEN,
        "last_price": float("nan"),
    }

    with (
        patch.object(live_chain, "current_nifty_price", 22500.0),
        patch.object(live_chain.state_manager, "update_nifty") as update_nifty,
        patch.object(
            live_chain,
            "subscribe_options_if_needed",
        ) as subscribe_options,
    ):
        ws = Mock()
        live_chain.on_ticks(ws, [invalid_nifty_tick])

        assert live_chain.current_nifty_price == 22500.0
        update_nifty.assert_not_called()
        subscribe_options.assert_not_called()

    print("[PASS] Invalid NIFTY tick ignored")

    # An invalid option price must be rejected before the
    # state manager is updated.
    invalid_option_tick = {
        "instrument_token": 123456,
        "last_price": float("inf"),
    }

    metadata = {
        "tradingsymbol": "TEST_OPTION",
        "strike": 22500.0,
        "expiry": "2026-10-13",
        "option_type": "CE",
    }

    with (
        patch.object(live_chain, "current_nifty_price", 22500.0),
        patch.object(live_chain.state_manager, "update") as update_option,
    ):
        live_chain.process_option_tick(invalid_option_tick, metadata)
        update_option.assert_not_called()

    print("[PASS] Invalid option tick rejected before state update")
    print("\nINVALID TICK TESTS: ALL PASSED")


if __name__ == "__main__":
    run_test()
