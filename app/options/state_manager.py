
from datetime import datetime
from math import isfinite
from zoneinfo import ZoneInfo

from app.options.state import OptionState, NiftyState
from app.options.tick_validation import is_valid_price


IST = ZoneInfo("Asia/Kolkata")


def _normalize_timestamp(value):
    """Normalize valid exchange timestamps to IST."""
    if value is None:
        return datetime.now(IST)

    if not isinstance(value, datetime):
        return None

    try:
        if value.tzinfo is None:
            value = value.replace(tzinfo=IST)
        else:
            value = value.astimezone(IST)

        if not isfinite(value.timestamp()):
            return None

        return value

    except (OverflowError, OSError, TypeError, ValueError):
        return None


def _parse_nonnegative_int(value):
    """Return a nonnegative integer, or None for invalid input."""
    if isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None

    if not isfinite(number) or number < 0 or not number.is_integer():
        return None

    return int(number)


class OptionStateManager:

    def __init__(self):
        self.states: dict[int, OptionState] = {}
        self.nifty = NiftyState()


    def reset(self):
        """Clear option and NIFTY history after a reconnect."""
        self.states.clear()
        self.nifty = NiftyState()


    def update(self, tick):
        """Update option state only when the tick is valid."""
        if not isinstance(tick, dict):
            return None

        raw_token = tick.get("instrument_token")

        if isinstance(raw_token, bool):
            return None

        try:
            token = int(raw_token)
        except (TypeError, ValueError, OverflowError):
            return None

        if token <= 0:
            return None

        price = tick.get("last_price")

        if not is_valid_price(price):
            return None

        timestamp = _normalize_timestamp(
            tick.get("exchange_timestamp")
        )

        if timestamp is None:
            return None

        existing_state = self.states.get(token)

        # Missing volume/OI means unavailable: preserve the last known
        # cumulative value instead of resetting it to zero.
        previous_volume = (
            existing_state.volume if existing_state else 0
        )
        previous_oi = existing_state.oi if existing_state else 0

        raw_volume = tick.get("volume_traded")
        raw_oi = tick.get("oi")

        volume = (
            previous_volume
            if raw_volume is None
            else _parse_nonnegative_int(raw_volume)
        )
        oi = (
            previous_oi
            if raw_oi is None
            else _parse_nonnegative_int(raw_oi)
        )

        if volume is None or oi is None:
            return None

        # Reject old ticks before creating or updating state.
        if (
                existing_state is not None
                and existing_state.last_update is not None
                and timestamp.timestamp()
                < existing_state.last_update.timestamp()
        ):
            return None

        state = existing_state

        if state is None:
            state = OptionState(instrument_token=token)
            self.states[token] = state

        state.add_snapshot(
            price=float(price),
            volume=volume,
            oi=oi,
            timestamp=timestamp,
        )

        return state

    def update_nifty(self, tick):
        """Update NIFTY history only for valid prices and timestamps."""
        if not isinstance(tick, dict):
            return None

        price = tick.get("last_price")

        if not is_valid_price(price):
            return None

        timestamp = _normalize_timestamp(
            tick.get("exchange_timestamp")
        )

        if timestamp is None:
            return None

        if self.nifty.history:
            latest_timestamp = self.nifty.history[-1][0]

            if timestamp.timestamp() < latest_timestamp.timestamp():
                return None

        self.nifty.add_snapshot(
            price=float(price),
            timestamp=timestamp,
        )

        return self.nifty

    def get(self, token):
        return self.states.get(token)

    def all(self):
        return self.states.values()

    def get_nifty(self):
        return self.nifty
