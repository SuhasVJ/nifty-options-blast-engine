from math import exp, log, sqrt

from scipy.optimize import brentq
from scipy.stats import norm


class OptionGreeks:

    def __init__(
            self,
            risk_free_rate: float = 0.06,
            dividend_yield: float = 0.0
    ):
        self.r = risk_free_rate
        self.q = dividend_yield

    def d1(
            self,
            spot: float,
            strike: float,
            time_to_expiry: float,
            volatility: float
    ) -> float:

        return (
                log(spot / strike)
                + (
                        self.r
                        - self.q
                        + 0.5 * volatility ** 2
                ) * time_to_expiry
        ) / (
                volatility * sqrt(time_to_expiry)
        )

    def d2(
            self,
            d1_value: float,
            volatility: float,
            time_to_expiry: float
    ) -> float:

        return d1_value - (
                volatility * sqrt(time_to_expiry)
        )

    def price(
            self,
            spot: float,
            strike: float,
            time_to_expiry: float,
            volatility: float,
            option_type: str
    ) -> float:

        d1 = self.d1(
            spot,
            strike,
            time_to_expiry,
            volatility
        )

        d2 = self.d2(
            d1,
            volatility,
            time_to_expiry
        )

        option_type = option_type.upper()

        if option_type == "CE":

            return (
                    spot * exp(-self.q * time_to_expiry)
                    * norm.cdf(d1)
                    - strike
                    * exp(-self.r * time_to_expiry)
                    * norm.cdf(d2)
            )

        elif option_type == "PE":

            return (
                    strike
                    * exp(-self.r * time_to_expiry)
                    * norm.cdf(-d2)
                    - spot
                    * exp(-self.q * time_to_expiry)
                    * norm.cdf(-d1)
            )

        raise ValueError(
            "option_type must be CE or PE"
        )

    def implied_volatility(
            self,
            market_price: float,
            spot: float,
            strike: float,
            time_to_expiry: float,
            option_type: str
    ) -> float:

        if market_price <= 0:
            return 0.0

        if time_to_expiry <= 0:
            return 0.0

        def objective(volatility):

            return (
                    self.price(
                        spot,
                        strike,
                        time_to_expiry,
                        volatility,
                        option_type
                    )
                    - market_price
            )

        try:

            return brentq(
                objective,
                0.0001,
                5.0
            )

        except ValueError:

            return 0.0

    def delta(
            self,
            spot,
            strike,
            time_to_expiry,
            volatility,
            option_type
    ):

        d1 = self.d1(
            spot,
            strike,
            time_to_expiry,
            volatility
        )

        if option_type.upper() == "CE":

            return (
                    exp(-self.q * time_to_expiry)
                    * norm.cdf(d1)
            )

        return (
                exp(-self.q * time_to_expiry)
                * (norm.cdf(d1) - 1)
        )

    def gamma(
            self,
            spot,
            strike,
            time_to_expiry,
            volatility
    ):

        d1 = self.d1(
            spot,
            strike,
            time_to_expiry,
            volatility
        )

        return (
                exp(-self.q * time_to_expiry)
                * norm.pdf(d1)
                / (
                        spot
                        * volatility
                        * sqrt(time_to_expiry)
                )
        )

    def vega(
            self,
            spot,
            strike,
            time_to_expiry,
            volatility
    ):

        d1 = self.d1(
            spot,
            strike,
            time_to_expiry,
            volatility
        )

        return (
                spot
                * exp(-self.q * time_to_expiry)
                * norm.pdf(d1)
                * sqrt(time_to_expiry)
                / 100
        )

    def theta(
            self,
            spot,
            strike,
            time_to_expiry,
            volatility,
            option_type
    ):

        d1 = self.d1(
            spot,
            strike,
            time_to_expiry,
            volatility
        )

        d2 = self.d2(
            d1,
            volatility,
            time_to_expiry
        )

        first_term = (
                -(
                        spot
                        * exp(-self.q * time_to_expiry)
                        * norm.pdf(d1)
                        * volatility
                )
                / (
                        2 * sqrt(time_to_expiry)
                )
        )

        if option_type.upper() == "CE":

            second_term = (
                    self.q
                    * spot
                    * exp(-self.q * time_to_expiry)
                    * norm.cdf(d1)
            )

            third_term = (
                    self.r
                    * strike
                    * exp(-self.r * time_to_expiry)
                    * norm.cdf(d2)
            )

            return (
                    first_term
                    - second_term
                    - third_term
            ) / 365

        second_term = (
                self.q
                * spot
                * exp(-self.q * time_to_expiry)
                * norm.cdf(-d1)
        )

        third_term = (
                self.r
                * strike
                * exp(-self.r * time_to_expiry)
                * norm.cdf(-d2)
        )

        return (
                first_term
                + second_term
                + third_term
        ) / 365