
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from app.options import live_chain


def make_candidate(
        symbol,
        option_type,
        updated_at,
        score=80.0,
):
    return {
        "updated_at": updated_at,
        "tradingsymbol": symbol,
        "option_type": option_type,
        "ltp": 125.50,
        "iv": 13.5,
        "delta": 0.55,
        "gamma": 0.0015,
        "price_change_30s": 2.5,
        "oi_change_30s": 1.2,
        "volume_change_30s": 500,
        "nifty_change_30s": 0.2,
        "score": score,
        "status": "STRONG",
    }


def run_test():
    test_candidates = {
        101: make_candidate("FRESH_CE", "CE", 80.0),
        102: make_candidate("STALE_CE", "CE", 69.9),
        103: make_candidate("BOUNDARY_PE", "PE", 70.0),
    }

    output = StringIO()

    with (
        patch.multiple(
            live_chain,
            latest_scores=test_candidates,
            current_nifty_price=22500.0,
            current_expiry="2026-10-13",
            current_atm=22500.0,
            CANDIDATE_MAX_AGE_SECONDS=30,
        ),
        patch(
            "app.options.live_chain.time.monotonic",
            return_value=100.0,
        ),
        redirect_stdout(output),
    ):
        live_chain.print_candidate_report()

    report = output.getvalue()

    # Updated 20 seconds ago: must remain.
    assert "FRESH_CE" in report, "Fresh candidate was incorrectly removed"
    assert 101 in test_candidates, "Fresh candidate missing from state"

    # Updated 30.1 seconds ago: must be removed.
    assert "STALE_CE" not in report, "Stale candidate appeared in report"
    assert 102 not in test_candidates, "Stale candidate was not removed"

    # Exactly 30 seconds old: current logic uses > 30, not >= 30.
    assert 103 in test_candidates, "Boundary candidate was incorrectly removed"

    print("[PASS] Fresh candidate retained")
    print("[PASS] Stale candidate removed")
    print("[PASS] Candidate exactly 30 seconds old retained")
    print("\nCANDIDATE FRESHNESS TEST: PASSED")


if __name__ == "__main__":
    run_test()
