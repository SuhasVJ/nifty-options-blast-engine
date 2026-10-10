
import threading
import time
from unittest.mock import patch

from app.options import live_chain


def run_test():
    stale_token = 987654322

    stale_candidate = {
        "updated_at": time.monotonic() - 60,
        "tradingsymbol": "TEST_BACKGROUND_CE",
        "option_type": "CE",
        "ltp": 100.0,
        "iv": 13.0,
        "delta": 0.5,
        "gamma": 0.0015,
        "price_change_30s": 2.0,
        "oi_change_30s": 1.0,
        "volume_change_30s": 100,
        "nifty_change_30s": 0.2,
        "score": 80.0,
        "status": "STRONG",
    }

    test_candidates = {stale_token: stale_candidate}
    stop_event = threading.Event()

    with patch.multiple(
            live_chain,
            latest_scores=test_candidates,
            CANDIDATE_MAX_AGE_SECONDS=2,
    ):
        worker = threading.Thread(
            target=live_chain.stale_candidate_cleanup_loop,
            args=(stop_event,),
            name="test-stale-cleanup",
            daemon=True,
        )

        worker.start()

        deadline = time.monotonic() + 4

        try:
            while (
                    stale_token in test_candidates
                    and time.monotonic() < deadline
            ):
                time.sleep(0.05)

            assert stale_token not in test_candidates, (
                "Background loop did not remove the stale candidate"
            )

            print("[PASS] Background loop removed stale candidate")
            print("[PASS] No report or market tick was required")

        finally:
            stop_event.set()
            worker.join(timeout=2)

        assert not worker.is_alive(), "Test cleanup thread did not stop"

    print("[PASS] Background cleanup thread stopped cleanly")
    print("\nBACKGROUND CLEANUP LOOP TEST: PASSED")


if __name__ == "__main__":
    run_test()

