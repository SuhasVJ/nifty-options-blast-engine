
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.options.state_manager import OptionStateManager
from app.options.greeks_service import GreeksService
from app.options.blast_score import BlastScoreEngine


IST = ZoneInfo("Asia/Kolkata")
NIFTY_50_TOKEN = 256265
TEST_STRIKE = 22500.0


def build_synthetic_market_data(manager, candidates, start_time):
    """Feed 60 seconds of deterministic synthetic market ticks."""

    print("\nGenerating synthetic market data...")

    for index in range(13):
        timestamp = start_time + timedelta(seconds=index * 5)

        # Simulate NIFTY falling from 22,620 to 22,500.
        nifty_price = 22620.0 - (index * 10.0)

        manager.update_nifty({
            "instrument_token": NIFTY_50_TOKEN,
            "exchange_timestamp": timestamp,
            "last_price": nifty_price,
        })

        # Volume accelerates during the latest 30-second interval.
        if index <= 6:
            volume = 10000 + index * 500
        else:
            volume = 13000 + (index - 6) * 1000

        oi = 1_000_000 + index * 5000

        for candidate in candidates:
            price = (
                    candidate["base_price"]
                    + index * candidate["price_step"]
            )

            manager.update({
                "instrument_token": candidate["token"],
                "exchange_timestamp": timestamp,
                "last_price": price,
                "volume_traded": volume,
                "oi": oi,
            })

    print("Synthetic data generated: 13 snapshots per instrument.")


def main():
    print("\n" + "=" * 60)
    print("NIFTY OPTIONS BLAST ENGINE - INTEGRATION TEST")
    print("=" * 60)

    manager = OptionStateManager()
    greeks_service = GreeksService()
    score_engine = BlastScoreEngine()

    candidates = [
        {
            "token": 900001,
            "tradingsymbol": "TEST_CE_FAST",
            "option_type": "CE",
            "strike": TEST_STRIKE,
            "base_price": 105.0,
            "price_step": 0.40,
        },
        {
            "token": 900002,
            "tradingsymbol": "TEST_CE_SLOW",
            "option_type": "CE",
            "strike": TEST_STRIKE,
            "base_price": 105.0,
            "price_step": 0.15,
        },
        {
            "token": 900003,
            "tradingsymbol": "TEST_PE_FAST",
            "option_type": "PE",
            "strike": TEST_STRIKE,
            "base_price": 105.0,
            "price_step": 0.40,
        },
    ]

    # Use a future expiry so the Greeks calculation has time value.
    expiry_date = datetime.now(IST).date() + timedelta(days=3)
    start_time = datetime.now(IST).replace(microsecond=0)

    build_synthetic_market_data(
        manager=manager,
        candidates=candidates,
        start_time=start_time,
    )

    # 1. Verify that the required history is available.
    nifty_state = manager.get_nifty()

    assert nifty_state.has_history(30), (
        "NIFTY 30-second history is not ready."
    )

    nifty_change_30s = nifty_state.price_change_pct(30)

    print("\n[PASS] NIFTY history readiness")
    print(f"NIFTY 30-second change: {nifty_change_30s:+.4f}%")

    results = []

    # 2. Run the Greeks and Blast Score pipeline for each option.
    for candidate in candidates:
        state = manager.get(candidate["token"])

        assert state is not None, (
            f"Missing state for {candidate['tradingsymbol']}"
        )

        assert state.has_history(5), "Missing 5-second history"
        assert state.has_history(30), "Missing 30-second history"
        assert state.has_history(60), "Missing 60-second history"

        greeks = greeks_service.calculate(
            spot=nifty_state.last_price,
            strike=candidate["strike"],
            option_price=state.last_price,
            option_type=candidate["option_type"],
            expiry_date=expiry_date,
        )

        assert greeks is not None, (
            f"Greeks calculation failed for "
            f"{candidate['tradingsymbol']}"
        )

        score_result = score_engine.calculate(
            option_type=candidate["option_type"],
            greeks=greeks,
            price_change_5s=state.price_change_pct(5),
            price_change_30s=state.price_change_pct(30),
            oi_change_pct_30s=state.oi_change_pct(30),
            volume_change_30s=state.volume_change(30),
            volume_acceleration=state.volume_acceleration(),
            nifty_change_pct_30s=nifty_change_30s,
            data_ready=True,
        )

        assert score_result["score"] is not None, (
            f"Score missing for {candidate['tradingsymbol']}"
        )

        assert 0 <= score_result["score"] <= 100, (
            f"Score outside valid range for "
            f"{candidate['tradingsymbol']}"
        )

        results.append({
            "symbol": candidate["tradingsymbol"],
            "option_type": candidate["option_type"],
            "ltp": state.last_price,
            "iv": greeks["iv"] * 100,
            "gamma": greeks["gamma"],
            "score": score_result["score"],
            "status": score_result["status"],
        })

        print(
            f"[PASS] {candidate['tradingsymbol']}: "
            f"history, Greeks and score calculated"
        )

    # 3. Verify ranking is in descending score order.
    print("\n" + "=" * 60)
    print("SYNTHETIC CANDIDATE RANKINGS")
    print("=" * 60)

    for option_type in ("CE", "PE"):
        ranked = sorted(
            [
                result
                for result in results
                if result["option_type"] == option_type
            ],
            key=lambda result: result["score"],
            reverse=True,
        )

        print(f"\n{option_type} candidates:")

        for rank, result in enumerate(ranked, start=1):
            print(
                f"{rank}. {result['symbol']} | "
                f"Score={result['score']:.2f}/100 | "
                f"{result['status']} | "
                f"LTP={result['ltp']:.2f} | "
                f"IV={result['iv']:.2f}% | "
                f"Gamma={result['gamma']:.6f}"
            )

        assert all(
            ranked[i]["score"] >= ranked[i + 1]["score"]
            for i in range(len(ranked) - 1)
        ), f"{option_type} ranking is not descending."

    assert len(results) == 3, (
        "Expected three scored synthetic candidates."
    )

    print("\n" + "=" * 60)
    print("INTEGRATION TEST: PASSED")
    print("State -> Greeks -> Blast Score -> Ranking")
    print("No live market connection was used.")
    print("=" * 60)


if __name__ == "__main__":
    main()
