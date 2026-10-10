
import math


def is_valid_price(value):
    """Return True only for finite, positive numeric prices."""
    if isinstance(value, bool):
        return False

    try:
        price = float(value)
    except (TypeError, ValueError, OverflowError):
        return False

    return math.isfinite(price) and price > 0
