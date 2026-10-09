
from datetime import datetime
from zoneinfo import ZoneInfo

from app.options.state import OptionState, NiftyState


IST = ZoneInfo("Asia/Kolkata")


class OptionStateManager:

    def __init__(self):

        self.states: dict[int, OptionState] = {}

        self.nifty = NiftyState()

    # ========================================================
    # OPTION
    # ========================================================

    def update(self, tick):

        token = tick["instrument_token"]

        state = self.states.get(token)

        if state is None:

            state = OptionState(
                instrument_token=token
            )

            self.states[token] = state

        timestamp = tick.get("exchange_timestamp")

        if timestamp is None:
            timestamp = datetime.now(IST)

        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(
                tzinfo=IST
            )

        price = tick.get("last_price") or 0.0
        volume = tick.get("volume_traded") or 0
        oi = tick.get("oi") or 0

        state.add_snapshot(
            price=price,
            volume=volume,
            oi=oi,
            timestamp=timestamp
        )

        return state

    # ========================================================
    # NIFTY
    # ========================================================

    def update_nifty(self, tick):

        timestamp = tick.get("exchange_timestamp")

        if timestamp is None:
            timestamp = datetime.now(IST)

        elif timestamp.tzinfo is None:
            timestamp = timestamp.replace(
                tzinfo=IST
            )

        price = tick.get("last_price") or 0.0

        self.nifty.add_snapshot(
            price=price,
            timestamp=timestamp
        )

        return self.nifty

    # ========================================================
    # GETTERS
    # ========================================================

    def get(self, token):

        return self.states.get(token)

    def all(self):

        return self.states.values()

    def get_nifty(self):

        return self.nifty
