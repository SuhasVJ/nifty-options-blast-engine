from math import exp, isfinite, log, sqrt

from scipy.optimize import brentq
from scipy.stats import norm


class OptionGreeks:
    """Black-Scholes option pricing and Greeks for European options.

    Volatility and implied volatility are expressed as decimal fractions:
    0.15 means 15%.
    """

    def __init__(
            self,
            risk_free_rate: float = 0.06,
            dividend_yield: float = 0.0,
    ):
        self.r = float(risk_free_rate)
        self.q = float(dividend_yield)

    @staticmethod
    def _valid_positive(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return False
        return isfinite(value) and value > 0

    def d1(
            self,
            spot: float,
            strike: float,
            time_to_expiry: float,
            volatility: float,
    ) -> float:
        if not all(self._valid_positive(v) for v in (
                spot, strike, time_to_expiry, volatility
        )):
            raise ValueError(
                "spot, strike, time_to_expiry, and volatility must be positive finite values"
            )

        return (
                log(spot / strike)
                + (self.r - self.q + 0.5 * volatility ** 2) * time_to_expiry
        ) / (volatility * sqrt(time_to_expiry))

    def d2(
            self,
            d1_value: float,
            volatility: float,
            time_to_expiry: float,
    ) -> float:
        return d1_value - volatility * sqrt(time_to_expiry)

    def price(
            self,
            spot: float,
            strike: float,
            time_to_expiry: float,
            volatility: float,
            option_type: str,
    ) -> float:
        option_type = str(option_type).strip().upper()
        if option_type not in ("CE", "PE"):
            raise ValueError("option_type must be CE or PE")

        d1_value = self.d1(spot, strike, time_to_expiry, volatility)
        d2_value = self.d2(d1_value, volatility, time_to_expiry)

        if option_type == "CE":
            return (
                    spot * exp(-self.q * time_to_expiry) * norm.cdf(d1_value)
                    - strike * exp(-self.r * time_to_expiry) * norm.cdf(d2_value)
            )

        return (
                strike * exp(-self.r * time_to_expiry) * norm.cdf(-d2_value)
                - spot * exp(-self.q * time_to_expiry) * norm.cdf(-d1_value)
        )

    def implied_volatility(
            self,
            market_price: float,
            spot: float,
            strike: float,
            time_to_expiry: float,
            option_type: str,
    ) -> float:
        """Return decimal IV, or 0.0 if no valid solution is available.

        Enforces European option no-arbitrage bounds before root finding.
        The IV search interval is 0.01% to 500% annualized volatility.
        """
        option_type = str(option_type).strip().upper()
        if option_type not in ("CE", "PE"):
            raise ValueError("option_type must be CE or PE")

        try:
            market_price = float(market_price)
            spot = float(spot)
            strike = float(strike)
            time_to_expiry = float(time_to_expiry)
        except (TypeError, ValueError):
            return 0.0

        if not all(isfinite(v) for v in (
                market_price, spot, strike, time_to_expiry
        )):
            return 0.0
        if market_price <= 0 or spot <= 0 or strike <= 0 or time_to_expiry <= 0:
            return 0.0

        discounted_spot = spot * exp(-self.q * time_to_expiry)
        discounted_strike = strike * exp(-self.r * time_to_expiry)

        if option_type == "CE":
            lower_bound = max(0.0, discounted_spot - discounted_strike)
            upper_bound = discounted_spot
        else:
            lower_bound = max(0.0, discounted_strike - discounted_spot)
            upper_bound = discounted_strike

        # Prices outside the model's feasible range cannot have a valid IV.
        if market_price < lower_bound - 1e-8 or market_price > upper_bound + 1e-8:
            return 0.0

        def objective(volatility):
            return (
                    self.price(
                        spot=spot,
                        strike=strike,
                        time_to_expiry=time_to_expiry,
                        volatility=volatility,
                        option_type=option_type,
                    )
                    - market_price
            )

        low_volatility = 0.0001
        high_volatility = 5.0

        try:
            low_value = objective(low_volatility)
            high_value = objective(high_volatility)

            if not isfinite(low_value) or not isfinite(high_value):
                return 0.0

            if abs(low_value) <= 1e-10:
                return low_volatility
            if abs(high_value) <= 1e-10:
                return high_volatility
            if low_value * high_value > 0:
                return 0.0

            result = brentq(
                objective,
                low_volatility,
                high_volatility,
                xtol=1e-8,
                maxiter=100,
            )
            return result if isfinite(result) and result > 0 else 0.0

        except (ValueError, RuntimeError, OverflowError, ZeroDivisionError):
            return 0.0

    def delta(
            self,
            spot,
            strike,
            time_to_expiry,
            volatility,
            option_type,
    ):
        option_type = str(option_type).strip().upper()
        if option_type not in ("CE", "PE"):
            raise ValueError("option_type must be CE or PE")

        d1_value = self.d1(spot, strike, time_to_expiry, volatility)

        if option_type == "CE":
            return exp(-self.q * time_to_expiry) * norm.cdf(d1_value)

        return exp(-self.q * time_to_expiry) * (norm.cdf(d1_value) - 1)

    def gamma(
            self,
            spot,
            strike,
            time_to_expiry,
            volatility,
    ):
        d1_value = self.d1(spot, strike, time_to_expiry, volatility)
        return (
                exp(-self.q * time_to_expiry)
                * norm.pdf(d1_value)
                / (spot * volatility * sqrt(time_to_expiry))
        )

    def vega(
            self,
            spot,
            strike,
            time_to_expiry,
            volatility,
    ):
        d1_value = self.d1(spot, strike, time_to_expiry, volatility)
        return (
                spot
                * exp(-self.q * time_to_expiry)
                * norm.pdf(d1_value)
                * sqrt(time_to_expiry)
                / 100
        )

    def theta(
            self,
            spot,
            strike,
            time_to_expiry,
            volatility,
            option_type,
    ):
        option_type = str(option_type).strip().upper()
        if option_type not in ("CE", "PE"):
            raise ValueError("option_type must be CE or PE")

        d1_value = self.d1(spot, strike, time_to_expiry, volatility)
        d2_value = self.d2(d1_value, volatility, time_to_expiry)

        first_term = (
                -spot
                * exp(-self.q * time_to_expiry)
                * norm.pdf(d1_value)
                * volatility
                / (2 * sqrt(time_to_expiry))
        )

        if option_type == "CE":
            second_term = (
                    self.q
                    * spot
                    * exp(-self.q * time_to_expiry)
                    * norm.cdf(d1_value)
            )
            third_term = (
                    self.r
                    * strike
                    * exp(-self.r * time_to_expiry)
                    * norm.cdf(d2_value)
            )
            return (first_term - second_term - third_term) / 365

        second_term = (
                self.q
                * spot
                * exp(-self.q * time_to_expiry)
                * norm.cdf(-d1_value)
        )
        third_term = (
                self.r
                * strike
                * exp(-self.r * time_to_expiry)
                * norm.cdf(-d2_value)
        )
        return (first_term + second_term + third_term) / 365
