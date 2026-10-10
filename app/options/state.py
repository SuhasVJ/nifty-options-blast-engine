
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite


@dataclass
class MarketSnapshot:
    timestamp: datetime
    price: float
    volume: int
    oi: int


def _safe_float(value, default=0.0):
    """Return a finite float, or a safe default."""
    try:
        result = float(value)
        return result if isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    """Convert market quantities safely to integers."""
    try:
        result = float(value)
        if not isfinite(result):
            return default
        return int(result)
    except (TypeError, ValueError, OverflowError):
        return default


def _reference_snapshot(history, latest_timestamp, seconds):
    """
    Find a historical snapshot at or before the requested target.

    A snapshot is accepted only if it is sufficiently close to the
    target time. This prevents stale data from being used silently.
    """
    if not history or latest_timestamp is None or seconds <= 0:
        return None

    latest_epoch = latest_timestamp.timestamp()
    target_epoch = latest_epoch - seconds

    # Permit limited timing variation, but reject stale references.
    tolerance = max(3.0, seconds * 0.25)

    closest = None
    closest_epoch = None

    for snapshot in history:
        snapshot_epoch = snapshot.timestamp.timestamp()

        # Only use a reference at or before the target.
        if snapshot_epoch > target_epoch:
            continue

        age_difference = target_epoch - snapshot_epoch

        if age_difference > tolerance:
            continue

        if closest_epoch is None or snapshot_epoch > closest_epoch:
            closest = snapshot
            closest_epoch = snapshot_epoch

    return closest


@dataclass
class OptionState:
    instrument_token: int

    # Latest market values
    last_price: float = 0.0
    volume: int = 0
    oi: int = 0

    # Keep recent history in memory.
    history: deque = field(
        default_factory=lambda: deque(maxlen=5000)
    )

    last_update: datetime | None = None

    def add_snapshot(
            self,
            price: float,
            volume: int,
            oi: int,
            timestamp: datetime,
    ):
        """Store a valid, chronological market snapshot."""
        if timestamp is None:
            return

        price = _safe_float(price)
        volume = max(0, _safe_int(volume))
        oi = max(0, _safe_int(oi))

        # Do not allow an older tick to overwrite newer state.
        if self.last_update is not None:
            if timestamp.timestamp() < self.last_update.timestamp():
                return

        self.last_price = price
        self.volume = volume
        self.oi = oi
        self.last_update = timestamp

        self.history.append(
            MarketSnapshot(
                timestamp=timestamp,
                price=price,
                volume=volume,
                oi=oi,
            )
        )

    def _snapshot_seconds_ago(self, seconds: int):
        """Return a sufficiently recent reference snapshot or None."""
        return _reference_snapshot(
            history=self.history,
            latest_timestamp=self.last_update,
            seconds=seconds,
        )


    def has_history(self, seconds: int) -> bool:
        """Return True only when a valid reference snapshot exists."""
        previous = self._snapshot_seconds_ago(seconds)

        if previous is None:
            return False

        if self.last_update is None:
            return False

        if self.last_update.timestamp() - previous.timestamp.timestamp() < seconds:
            return False

        return True


    # --------------------------------------------------------
    # PRICE MOMENTUM
    # --------------------------------------------------------

    def price_change_pct(self, seconds: int) -> float:
        previous = self._snapshot_seconds_ago(seconds)

        if previous is None or previous.price <= 0:
            return 0.0

        return (
                (self.last_price - previous.price)
                / previous.price
        ) * 100.0

    # --------------------------------------------------------
    # OPEN INTEREST CHANGE
    # --------------------------------------------------------

    def oi_change(self, seconds: int) -> int:
        previous = self._snapshot_seconds_ago(seconds)

        if previous is None:
            return 0

        return self.oi - previous.oi

    def oi_change_pct(self, seconds: int) -> float:
        previous = self._snapshot_seconds_ago(seconds)

        if previous is None or previous.oi <= 0:
            return 0.0

        return (
                (self.oi - previous.oi)
                / previous.oi
        ) * 100.0

    # --------------------------------------------------------
    # TRADED VOLUME CHANGE
    # --------------------------------------------------------

    def volume_change(self, seconds: int) -> int:
        previous = self._snapshot_seconds_ago(seconds)

        if previous is None:
            return 0

        change = self.volume - previous.volume

        # Cumulative volume can reset or be corrected.
        # Do not report a negative quantity as traded volume.
        return max(0, change)

    # --------------------------------------------------------
    # VOLUME ACCELERATION
    # --------------------------------------------------------

    def volume_acceleration(self) -> float:
        """
        Compare volume traded in the latest 30-second interval
        with volume traded in the preceding 30-second interval.

        Returns zero when reference data is unavailable or when
        the preceding interval has no positive volume.
        """
        previous_30s = self._snapshot_seconds_ago(30)
        previous_60s = self._snapshot_seconds_ago(60)

        if previous_30s is None or previous_60s is None:
            return 0.0

        recent_volume = self.volume - previous_30s.volume
        older_volume = previous_30s.volume - previous_60s.volume

        if recent_volume < 0 or older_volume <= 0:
            return 0.0

        return recent_volume / older_volume


@dataclass
class NiftyState:
    last_price: float = 0.0

    # Each item is (timestamp, price).
    history: deque = field(
        default_factory=lambda: deque(maxlen=5000)
    )

    def add_snapshot(
            self,
            price: float,
            timestamp: datetime,
    ):
        """Store a valid, chronological NIFTY snapshot."""
        if timestamp is None:
            return

        price = _safe_float(price)

        if price <= 0:
            return

        if self.history:
            previous_timestamp = self.history[-1][0]

            if timestamp.timestamp() < previous_timestamp.timestamp():
                return

        self.last_price = price
        self.history.append((timestamp, price))

    def price_change_pct(self, seconds: int) -> float:
        if not self.history:
            return 0.0

        latest_timestamp = self.history[-1][0]

        # Reuse the same time-window validation as option state.
        snapshots = [
            MarketSnapshot(
                timestamp=timestamp,
                price=price,
                volume=0,
                oi=0,
            )
            for timestamp, price in self.history
        ]

        previous = _reference_snapshot(
            history=snapshots,
            latest_timestamp=latest_timestamp,
            seconds=seconds,
        )

        if previous is None or previous.price <= 0:
            return 0.0

        return (
                (self.last_price - previous.price)
                / previous.price
        ) * 100.0

    def has_history(self, seconds: int) -> bool:
        """Return True only when NIFTY has a valid reference snapshot."""
        if not self.history:
            return False

        latest_timestamp = self.history[-1][0]

        snapshots = [
            MarketSnapshot(
                timestamp=timestamp,
                price=price,
                volume=0,
                oi=0,
            )
            for timestamp, price in self.history
        ]

        previous = _reference_snapshot(
            history=snapshots,
            latest_timestamp=latest_timestamp,
            seconds=seconds,
        )

        return previous is not None
