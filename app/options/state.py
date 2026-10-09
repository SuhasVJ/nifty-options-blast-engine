from dataclasses import dataclass, field
from datetime import datetime
from collections import deque


@dataclass
class MarketSnapshot:
    timestamp: datetime
    price: float
    volume: int
    oi: int


@dataclass
class OptionState:

    instrument_token: int

    # Current values
    last_price: float = 0.0
    volume: int = 0
    oi: int = 0

    # Historical snapshots
    history: deque = field(
        default_factory=lambda: deque(maxlen=300)
    )

    last_update: datetime | None = None

    def add_snapshot(
            self,
            price: float,
            volume: int,
            oi: int,
            timestamp: datetime
    ):
        """
        Store a market snapshot.
        """

        self.last_price = price
        self.volume = volume
        self.oi = oi
        self.last_update = timestamp

        self.history.append(
            MarketSnapshot(
                timestamp=timestamp,
                price=price,
                volume=volume,
                oi=oi
            )
        )

    def _snapshot_seconds_ago(
            self,
            seconds: int
    ):
        """
        Find the snapshot closest to the requested
        number of seconds ago.
        """

        if not self.history:
            return None

        target_time = (
                self.last_update.timestamp() - seconds
        )

        closest = None
        smallest_difference = float("inf")

        for snapshot in self.history:

            difference = abs(
                snapshot.timestamp.timestamp()
                - target_time
            )

            if difference < smallest_difference:
                smallest_difference = difference
                closest = snapshot

        return closest

    # ========================================================
    # PRICE MOMENTUM
    # ========================================================

    def price_change_pct(
            self,
            seconds: int
    ) -> float:

        previous = self._snapshot_seconds_ago(seconds)

        if previous is None:
            return 0.0

        if previous.price <= 0:
            return 0.0

        return (
                (self.last_price - previous.price)
                / previous.price
        ) * 100

    # ========================================================
    # OI CHANGE
    # ========================================================

    def oi_change(
            self,
            seconds: int
    ) -> int:

        previous = self._snapshot_seconds_ago(seconds)

        if previous is None:
            return 0

        return self.oi - previous.oi

    def oi_change_pct(
            self,
            seconds: int
    ) -> float:

        previous = self._snapshot_seconds_ago(seconds)

        if previous is None:
            return 0.0

        if previous.oi <= 0:
            return 0.0

        return (
                (self.oi - previous.oi)
                / previous.oi
        ) * 100

    # ========================================================
    # VOLUME CHANGE
    # ========================================================

    def volume_change(
            self,
            seconds: int
    ) -> int:

        previous = self._snapshot_seconds_ago(seconds)

        if previous is None:
            return 0

        return self.volume - previous.volume

    # ========================================================
    # VOLUME ACCELERATION
    # ========================================================

    def volume_acceleration(
            self
    ) -> float:

        previous_30s = self._snapshot_seconds_ago(30)
        previous_60s = self._snapshot_seconds_ago(60)

        if previous_30s is None:
            return 0.0

        if previous_60s is None:
            return 0.0

        recent_volume = (
                self.volume - previous_30s.volume
        )

        older_volume = (
                previous_30s.volume
                - previous_60s.volume
        )

        if older_volume <= 0:
            return 0.0

        return (
                recent_volume / older_volume
        )


@dataclass
class NiftyState:

    last_price: float = 0.0

    history: deque = field(
        default_factory=lambda: deque(maxlen=300)
    )

    def add_snapshot(
            self,
            price: float,
            timestamp: datetime
    ):

        self.last_price = price

        self.history.append(
            (
                timestamp,
                price
            )
        )

    def price_change_pct(
            self,
            seconds: int
    ) -> float:

        if not self.history:
            return 0.0

        target_time = (
                self.history[-1][0].timestamp()
                - seconds
        )

        closest = None
        smallest_difference = float("inf")

        for timestamp, price in self.history:

            difference = abs(
                timestamp.timestamp()
                - target_time
            )

            if difference < smallest_difference:
                smallest_difference = difference
                closest = price

        if closest is None or closest <= 0:
            return 0.0

        return (
                (self.last_price - closest)
                / closest
        ) * 100