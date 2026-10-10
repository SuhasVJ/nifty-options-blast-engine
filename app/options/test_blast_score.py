
from app.options.blast_score import BlastScoreEngine


def main():
    engine = BlastScoreEngine()

    greeks = {
        "iv": 0.13,
        "delta": 0.50,
        "gamma": 0.0014,
    }

    bullish = engine.calculate(
        option_type="CE",
        greeks=greeks,
        price_change_5s=0.15,
        price_change_30s=0.40,
        oi_change_pct_30s=0.60,
        volume_change_30s=12000,
        volume_acceleration=2.5,
        nifty_change_pct_30s=0.15,
        data_ready=True,
    )

    bearish = engine.calculate(
        option_type="PE",
        greeks=greeks,
        price_change_5s=0.12,
        price_change_30s=0.35,
        oi_change_pct_30s=0.50,
        volume_change_30s=9000,
        volume_acceleration=2.0,
        nifty_change_pct_30s=-0.12,
        data_ready=True,
    )

    insufficient = engine.calculate(
        option_type="CE",
        greeks=greeks,
        price_change_5s=0,
        price_change_30s=0,
        oi_change_pct_30s=0,
        volume_change_30s=0,
        volume_acceleration=0,
        nifty_change_pct_30s=0,
        data_ready=False,
    )

    print("BULLISH TEST:", bullish)
    print("BEARISH TEST:", bearish)
    print("INSUFFICIENT DATA TEST:", insufficient)

    assert bullish["score"] is not None
    assert 0 <= bullish["score"] <= 100
    assert bullish["bias"] == "BULLISH"

    assert bearish["score"] is not None
    assert 0 <= bearish["score"] <= 100
    assert bearish["bias"] == "BEARISH"

    assert insufficient["score"] is None
    assert insufficient["status"] == "INSUFFICIENT_DATA"

    print("\nAll Blast Score tests passed.")


if __name__ == "__main__":
    main()
