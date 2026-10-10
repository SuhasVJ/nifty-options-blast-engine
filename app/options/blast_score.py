
from math import isfinite


def _number(value, default=0.0):
    """Convert a value to a finite float safely."""
    try:
        result = float(value)
        return result if isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _clamp(value, minimum=0.0, maximum=1.0):
    return max(minimum, min(maximum, value))


class BlastScoreEngine:
    """
    Rule-based NIFTY option screening score.

    This is a research/scanning score, not a probability of profit
    or an automatic trading recommendation.
    """

    WEIGHTS = {
        "delta": 15,
        "iv": 10,
        "gamma": 15,
        "price_momentum": 25,
        "oi_confirmation": 15,
        "volume_acceleration": 10,
        "nifty_alignment": 10,
    }

    def calculate(
            self,
            *,
            option_type,
            greeks,
            price_change_5s,
            price_change_30s,
            oi_change_pct_30s,
            volume_change_30s,
            volume_acceleration,
            nifty_change_pct_30s,
            data_ready=False,
    ):
        """
        Greeks IV must be a decimal: 0.15 means 15%.

        data_ready must be True only when sufficient, recent market
        history is available. Synthetic test data can also set it True.
        """
        option_type = str(option_type).strip().upper()

        if option_type not in ("CE", "PE"):
            raise ValueError("option_type must be CE or PE")

        greeks = greeks or {}

        delta = abs(_number(greeks.get("delta")))
        iv = _number(greeks.get("iv"))
        gamma = _number(greeks.get("gamma"))

        p5 = _number(price_change_5s)
        p30 = _number(price_change_30s)
        oi30 = _number(oi_change_pct_30s)
        volume30 = _number(volume_change_30s)
        acceleration = _number(volume_acceleration)
        nifty30 = _number(nifty_change_pct_30s)

        # 1. Delta: prefer reasonably responsive options.
        # Full score near 0.50; reduce for very low/high absolute delta.
        delta_quality = _clamp(1 - abs(delta - 0.50) / 0.50)
        delta_score = 15 * delta_quality

        # 2. IV: full score at or below 15%; fade to zero at 25%.
        if iv <= 0:
            iv_score = 0
        else:
            iv_score = 10 * _clamp((0.25 - iv) / 0.10)

        # 3. Gamma: user's initial target was above 0.0012.
        gamma_score = 15 * _clamp(gamma / 0.0012)

        # 4. Option premium momentum: reward positive movement.
        # 20 points for 30s momentum; 5 for positive 5s confirmation.
        momentum_score = (
                20 * _clamp(p30 / 0.50)
                + (5 if p5 > 0 else 0)
        )

        # 5. OI confirmation: positive price momentum plus rising OI
        # can be consistent with long buildup, but is not conclusive.
        if p30 > 0 and oi30 > 0:
            oi_score = 15 * _clamp(oi30 / 1.0)
        else:
            oi_score = 0

        # 6. Volume acceleration: compare recent volume activity
        # with the preceding interval. Ignore negative volume deltas.
        if volume30 <= 0:
            volume_score = 0
        else:
            volume_score = 10 * _clamp(
                (acceleration - 1.0) / 2.0
            )

        # 7. Underlying confirmation: CE favours rising NIFTY;
        # PE favours falling NIFTY.
        aligned_move = (
            nifty30 if option_type == "CE" else -nifty30
        )
        nifty_score = 10 * _clamp(aligned_move / 0.20)

        components = {
            "delta": round(delta_score, 2),
            "iv": round(iv_score, 2),
            "gamma": round(gamma_score, 2),
            "price_momentum": round(momentum_score, 2),
            "oi_confirmation": round(oi_score, 2),
            "volume_acceleration": round(volume_score, 2),
            "nifty_alignment": round(nifty_score, 2),
        }

        if not data_ready:
            return {
                "score": None,
                "status": "INSUFFICIENT_DATA",
                "option_type": option_type,
                "bias": "BULLISH" if option_type == "CE" else "BEARISH",
                "components": components,
                "message": (
                    "Score withheld until sufficient recent market "
                    "history is available."
                ),
            }

        # Hard eligibility filters: reject options outside the user's criteria.
        # GreeksService expresses IV as a decimal (0.15 = 15%).
        if (
                delta <= 0.30
                or not (0 < iv < 0.15)
                or gamma <= 0.0012
        ):
            return {
                "score": None,
                "status": "FILTERED",
                "option_type": option_type,
                "bias": "BULLISH" if option_type == "CE" else "BEARISH",
                "components": components,
                "message": (
                    "Option rejected: requires absolute delta > 0.30, "
                    "IV between 0 and 0.15, and gamma > 0.0012."
                ),
            }

        score = round(sum(components.values()), 2)
        score = min(100.0, max(0.0, score))

        if score >= 75:
            status = "STRONG"
        elif score >= 55:
            status = "MODERATE"
        else:
            status = "WEAK"

        return {
            "score": score,
            "status": status,
            "option_type": option_type,
            "bias": "BULLISH" if option_type == "CE" else "BEARISH",
            "components": components,
            "message": (
                "Screening score only; not a probability of profit "
                "or a trade instruction."
            ),
        }
