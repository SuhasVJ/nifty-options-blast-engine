"""Independent thread-safe Natural Gas dashboard state."""
import threading
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

_lock = threading.RLock()
_state = {
    "updated_at": None,
    "natural_gas": {
        "connected": False, "instrument": "MCX Natural Gas futures", "symbol": None,
        "expiry": None, "ltp": None, "last_data_time": None, "status": "STOPPED",
        "message": "Natural Gas scanner not started",
        "signals": {"intraday": None, "swing": None}, "history": [],
        "data_source": "Zerodha Kite Connect historical candles",
    },
}


def publish_natural_gas(payload):
    with _lock:
        _state["natural_gas"].update(deepcopy(payload))
        _state["updated_at"] = datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")


def get_payload():
    with _lock:
        return deepcopy(_state)
