
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pandas as pd

from app.options import live_chain


IST = ZoneInfo("Asia/Kolkata")
EXPIRY = date(2026, 10, 13)



class FakeWebSocket:
    MODE_FULL = "full"
    MODE_QUOTE = "quote"

    def __init__(self, fail_operation):
        self.fail_operation = fail_operation
        self.failed_once = False
        self.subscribe_calls = 0
        self.set_mode_calls = 0
        self.unsubscribe_calls = 0

        # Simulate a previously subscribed option.
        self.subscribed_tokens = {999: self.MODE_FULL}

    def unsubscribe(self, tokens):
        self.unsubscribe_calls += 1

        if not self.failed_once and self.fail_operation == "unsubscribe":
            self.failed_once = True
            raise RuntimeError("Simulated unsubscribe failure")

        for token in tokens:
            self.subscribed_tokens.pop(token, None)

    def subscribe(self, tokens):
        self.subscribe_calls += 1

        if not self.failed_once and self.fail_operation == "subscribe":
            self.failed_once = True
            raise RuntimeError("Simulated subscribe failure")

        for token in tokens:
            self.subscribed_tokens[token] = self.MODE_QUOTE

    def set_mode(self, mode, tokens):
        self.set_mode_calls += 1

        if not self.failed_once and self.fail_operation == "set_mode":
            self.failed_once = True
            raise RuntimeError("Simulated set_mode failure")

        for token in tokens:
            self.subscribed_tokens[token] = mode

def run_failure_and_retry_test(fail_operation):
    # Synthetic instrument master and option chain.
    instruments = pd.DataFrame([
        {"expiry": EXPIRY, "strike": 100.0},
        {"expiry": EXPIRY, "strike": 110.0},
    ])

    chain = pd.DataFrame([
        {
            "instrument_token": 111,
            "tradingsymbol": "TEST100CE",
            "strike": 100.0,
            "expiry": EXPIRY,
            "instrument_type": "CE",
        },
        {
            "instrument_token": 222,
            "tradingsymbol": "TEST100PE",
            "strike": 100.0,
            "expiry": EXPIRY,
            "instrument_type": "PE",
        },
    ])

    ws = FakeWebSocket(fail_operation)

    # Simulate a previously tracked option universe.
    live_chain.instrument_df = instruments
    live_chain.current_atm = None
    live_chain.current_expiry = None
    live_chain.current_nifty_price = 0.0
    live_chain.subscribed_option_tokens = {999}
    live_chain.instrument_metadata = {
        999: {
            "tradingsymbol": "OLD_OPTION",
            "strike": 100.0,
            "expiry": EXPIRY,
            "option_type": "CE",
        }
    }

    live_chain.latest_scores.clear()
    live_chain.latest_scores[999] = {
        "updated_at": 9999999999.0,
        "tradingsymbol": "OLD_OPTION",
        "option_type": "CE",
        "score": 90.0,
        "status": "STRONG",
    }

    nifty_tick = {
        "instrument_token": live_chain.NIFTY_50_TOKEN,
        "last_price": 22000.0,
        "exchange_timestamp": datetime.now(IST),
    }

    fake_nifty_state = SimpleNamespace(last_price=22000.0)

    with (
        patch.object(
            live_chain.state_manager,
            "update_nifty",
            return_value=fake_nifty_state,
        ),
        patch.object(
            live_chain,
            "get_nearest_expiry",
            return_value=EXPIRY,
        ),
        patch.object(
            live_chain,
            "get_atm_strike",
            return_value=100.0,
        ),
        patch.object(
            live_chain,
            "get_option_chain",
            return_value=(chain, EXPIRY, 100.0),
        ),
    ):
        # First NIFTY tick: the simulated WebSocket operation fails.
        live_chain.on_ticks(ws, [nifty_tick])

        assert ws.failed_once, (
            f"Expected {fail_operation!r} failure did not occur. "
            f"Calls: unsubscribe={ws.unsubscribe_calls}, "
            f"subscribe={ws.subscribe_calls}, "
            f"set_mode={ws.set_mode_calls}. "
            f"SDK subscriptions={ws.subscribed_tokens}"
        )
        assert live_chain.instrument_metadata == {}
        assert live_chain.latest_scores == {}

        print(
            f"[PASS] {fail_operation}: failure invalidates "
            "metadata and old candidates"
        )

        # An option tick must not create a candidate while metadata
        # is unavailable.
        live_chain.on_ticks(ws, [{
            "instrument_token": 111,
            "last_price": 10.0,
        }])

        assert live_chain.latest_scores == {}
        print("[PASS] Option tick ignored while metadata is invalid")

        # Next NIFTY tick: retry the option-chain update.
        live_chain.on_ticks(ws, [nifty_tick])

        assert set(live_chain.instrument_metadata) == {111, 222}
        assert live_chain.subscribed_option_tokens == {111, 222}
        assert live_chain.current_atm == 100.0
        assert live_chain.current_expiry == EXPIRY

        assert ws.failed_once
        assert ws.subscribe_calls >= 1
        assert ws.set_mode_calls >= 1

        assert all(
            ws.subscribed_tokens[token] == ws.MODE_FULL
            for token in {111, 222}
        )
        assert 999 not in ws.subscribed_tokens

        if fail_operation == "set_mode":
            assert ws.subscribe_calls == 1, (
                "Retry should correct the mode without resubscribing tokens"
            )

        print("[PASS] Subsequent NIFTY tick restores option metadata")
        print("[PASS] Subscription retry completed")


def main():
    original_interval = live_chain.REPORT_INTERVAL_SECONDS

    try:
        # Prevent periodic report timing from affecting this test.
        live_chain.REPORT_INTERVAL_SECONDS = 10**9

        for operation in ("unsubscribe", "subscribe", "set_mode"):
            run_failure_and_retry_test(operation)

        print("\nSUBSCRIPTION RECOVERY TESTS: ALL PASSED")

    finally:
        live_chain.REPORT_INTERVAL_SECONDS = original_interval
        live_chain.instrument_df = None
        live_chain.state_manager.reset()
        live_chain.reset_subscription_state()
        live_chain.current_nifty_price = 0.0
        live_chain.latest_scores.clear()


if __name__ == "__main__":
    main()
