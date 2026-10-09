from datetime import datetime, date, time
from zoneinfo import ZoneInfo

from app.options.greeks import OptionGreeks


IST = ZoneInfo("Asia/Kolkata")
EXPIRY_TIME = time(15, 30)


class GreeksService:

    def __init__(self, risk_free_rate=0.06, dividend_yield=0.0):
        self.engine = OptionGreeks(
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield
        )

    def time_to_expiry(self, expiry_date, now=None):
        """
        Calculate exact time to NIFTY option expiry in years.

        Expiry assumed at 15:30 IST on expiry date.
        """

        if isinstance(expiry_date, datetime):
            expiry_date = expiry_date.date()

        if not isinstance(expiry_date, date):
            expiry_date = expiry_date.to_pydatetime().date()

        if now is None:
            now = datetime.now(IST)

        expiry_datetime = datetime.combine(
            expiry_date,
            EXPIRY_TIME,
            tzinfo=IST
        )

        seconds_remaining = (
                expiry_datetime - now
        ).total_seconds()

        if seconds_remaining <= 0:
            return 0.0

        return seconds_remaining / (365 * 24 * 60 * 60)

    def calculate(
            self,
            spot,
            strike,
            option_price,
            option_type,
            expiry_date
    ):
        time_to_expiry = self.time_to_expiry(expiry_date)

        if spot <= 0:
            return None

        if strike <= 0:
            return None

        if option_price <= 0:
            return None

        if time_to_expiry <= 0:
            return None

        iv = self.engine.implied_volatility(
            spot,
            strike,
            option_price,
            time_to_expiry,
            option_type
        )

        if iv <= 0:
            return None

        delta = self.engine.delta(
            spot,
            strike,
            iv,
            time_to_expiry,
            option_type
        )

        gamma = self.engine.gamma(
            spot,
            strike,
            iv,
            time_to_expiry
        )

        vega = self.engine.vega(
            spot,
            strike,
            iv,
            time_to_expiry
        )

        theta = self.engine.theta(
            spot,
            strike,
            iv,
            time_to_expiry,
            option_type
        )

        return {
            "iv": iv,
            "delta": delta,
            "gamma": gamma,
            "vega": vega,
            "theta": theta,
            "time_to_expiry": time_to_expiry,
            "days_to_expiry": time_to_expiry * 365
        }