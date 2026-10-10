
import time
from unittest.mock import patch

from app.options import live_chain


def run_test():
    stale_token = 987654321

    stale_candidate = {
        "updated_at": time.monotonic() - 60,
        "tradingsymbol": "TEST_STALE_CE",
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

    with patch.object(
            live_chain,
            "latest_scores",
            test_candidates,
    ):
        removed = live_chain.cleanup_stale_candidates()

        assert removed == 1, (
            f"Expected 1 stale candidate removed, got {removed}"
        )
        assert stale_token not in test_candidates, (
            "Stale candidate still exists"
        )

    print("[PASS] Stale candidate removed without printing a report")
    print("\nBACKGROUND CLEANUP TEST: PASSED")


if __name__ == "__main__":
    run_test()
