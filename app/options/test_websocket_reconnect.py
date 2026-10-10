
from unittest.mock import Mock, patch

import pandas as pd

from app.options import live_chain


def test_nifty_resubscription_after_reconnect():
    ws = Mock()
    ws.MODE_FULL = "full"

    with (
        patch.object(
            live_chain,
            "subscribed_option_tokens",
            {111},
        ),
        patch.object(
            live_chain,
            "instrument_metadata",
            {111: {"tradingsymbol": "OLD_OPTION"}},
        ),
        patch.object(live_chain, "current_atm", 22500.0),
        patch.object(live_chain, "current_expiry", "OLD_EXPIRY"),
        patch.object(live_chain, "current_nifty_price", 22500.0),
    ):
        live_chain.on_connect(ws, response=None)

        ws.subscribe.assert_called_once_with(
            [live_chain.NIFTY_50_TOKEN]
        )
        ws.set_mode.assert_called_once_with(
            ws.MODE_FULL,
            [live_chain.NIFTY_50_TOKEN],
        )

        assert live_chain.current_atm is None
        assert live_chain.current_expiry is None
        assert live_chain.current_nifty_price == 0.0
        assert not live_chain.subscribed_option_tokens
        assert not live_chain.instrument_metadata

    print("[PASS] Reconnect resets state and subscribes to NIFTY 50")


def test_option_subscriptions_rebuilt():
    ws = Mock()
    ws.MODE_FULL = "full"

    expiry = pd.Timestamp("2026-10-13").date()

    instruments = pd.DataFrame([
        {
            "instrument_token": 201,
            "tradingsymbol": "TEST_CE",
            "strike": 22500.0,
            "expiry": expiry,
            "instrument_type": "CE",
        },
        {
            "instrument_token": 202,
            "tradingsymbol": "TEST_PE",
            "strike": 22500.0,
            "expiry": expiry,
            "instrument_type": "PE",
        },
    ])

    chain = instruments.copy()

    with (
        patch.object(live_chain, "instrument_df", instruments),
        patch.object(
            live_chain,
            "get_nearest_expiry",
            return_value=expiry,
        ),
        patch.object(
            live_chain,
            "get_atm_strike",
            return_value=22500.0,
        ),
        patch.object(
            live_chain,
            "get_option_chain",
            return_value=(chain, expiry, 22500.0),
        ),
        patch.object(live_chain, "current_atm", None),
        patch.object(live_chain, "current_expiry", None),
        patch.object(live_chain, "subscribed_option_tokens", set()),
        patch.object(live_chain, "instrument_metadata", {}),
        patch.object(live_chain, "latest_scores", {}),
    ):
        live_chain.subscribe_options_if_needed(ws, 22500.0)

        # Both synthetic option tokens should be subscribed.
        ws.subscribe.assert_called_once()
        subscribed_tokens = set(ws.subscribe.call_args.args[0])
        assert subscribed_tokens == {201, 202}

        # Both options should be set to full mode.
        ws.set_mode.assert_called_once_with(
            ws.MODE_FULL,
            [201, 202],
        )

        assert live_chain.subscribed_option_tokens == {201, 202}
        assert set(live_chain.instrument_metadata) == {201, 202}
        assert live_chain.current_atm == 22500.0
        assert live_chain.current_expiry == expiry

    print("[PASS] Option subscriptions rebuilt after reconnect")


def run_test():
    test_nifty_resubscription_after_reconnect()
    test_option_subscriptions_rebuilt()
    print("\nWEBSOCKET RECONNECT TESTS: ALL PASSED")


if __name__ == "__main__":
    run_test()
