
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.options.greeks import OptionGreeks


IST = ZoneInfo("Asia/Kolkata")
EXPIRY_TIME = time(15, 30)


class GreeksService:

    def __init__(self, risk_free_rate=0.06, dividend_yield=0.0):
        self.engine = OptionGreeks(
            risk_free_rate=risk_free_rate,
            dividend_yield=dividend_yield,
        )

    def time_to_expiry(self, expiry_date, now=None):
        """Return time until expiry in years, using 15:30 IST."""

        if isinstance(expiry_date, datetime):
            expiry_date = expiry_date.date()
        elif not isinstance(expiry_date, date):
            expiry_date = expiry_date.to_pydatetime().date()

        if now is None:
            now = datetime.now(IST)
        elif now.tzinfo is None:
            now = now.replace(tzinfo=IST)

        expiry_datetime = datetime.combine(
            expiry_date,
            EXPIRY_TIME,
            tzinfo=IST,
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
            expiry_date,
    ):
        if spot <= 0 or strike <= 0 or option_price <= 0:
            return None

        option_type = option_type.upper()
        if option_type not in ("CE", "PE"):
            raise ValueError("option_type must be CE or PE")

        time_to_expiry = self.time_to_expiry(expiry_date)

        if time_to_expiry <= 0:
            return None

        # Signature: market_price, spot, strike, time, option_type
        iv = self.engine.implied_volatility(
            market_price=option_price,
            spot=spot,
            strike=strike,
            time_to_expiry=time_to_expiry,
            option_type=option_type,
        )

        if iv <= 0:
            return None

        # All Greek methods receive time_to_expiry before volatility.
        delta = self.engine.delta(
            spot, strike, time_to_expiry, iv, option_type
        )

        gamma = self.engine.gamma(
            spot, strike, time_to_expiry, iv
        )

        vega = self.engine.vega(
            spot, strike, time_to_expiry, iv
        )

        theta = self.engine.theta(
            spot, strike, time_to_expiry, iv, option_type
        )

        return {
            "iv": iv,
            "delta": delta,
            "gamma": gamma,
            "vega": vega,
            "theta": theta,
            "time_to_expiry": time_to_expiry,
            "days_to_expiry": time_to_expiry * 365,
        }
