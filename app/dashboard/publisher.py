"""Thread-safe data and console-event publisher for the local dashboard."""
import sys
import threading
from collections import deque
from copy import deepcopy
from datetime import datetime
from zoneinfo import ZoneInfo

_lock = threading.RLock()
_events = deque(maxlen=500)
_event_id = 0
_state = {
    "updated_at": None,
    "market": {"nifty": None, "expiry": None, "atm": None, "connected": False, "last_tick_time": None},
    "candidates": {"CE": [], "PE": []},
    "diagnostics": {"statuses": {}, "filtered_by_type": {"CE": 0, "PE": 0}, "counters": {}},
}

def _now():
    return datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")

def publish_snapshot(payload):
    with _lock:
        for section, values in payload.items():
            if section in ("market", "candidates", "diagnostics") and isinstance(values, dict):
                _state.setdefault(section, {}).update(deepcopy(values))
            else:
                _state[section] = deepcopy(values)
        _state["updated_at"] = _now()

def publish_report(candidates, nifty, expiry, atm):
    grouped = {"CE": [], "PE": []}
    for c in candidates:
        side = str(c.get("option_type", "")).upper()
        if side not in grouped:
            continue
        item = {k: c.get(k) for k in (
            "tradingsymbol", "option_type", "score", "status", "ltp", "iv", "delta",
            "gamma", "price_change_30s", "oi_change_30s", "nifty_change_30s")}
        grouped[side].append(item)
    for side in grouped:
        grouped[side].sort(key=lambda x: float(x.get("score") or -1), reverse=True)
        grouped[side] = grouped[side][:10]
    publish_snapshot({"market": {"nifty": nifty, "expiry": str(expiry) if expiry is not None else None, "atm": atm},
                      "candidates": grouped})

def publish_diagnostics(statuses=None, filtered_by_type=None, counters=None):
    d = {}
    if statuses is not None: d["statuses"] = statuses
    if filtered_by_type is not None: d["filtered_by_type"] = filtered_by_type
    if counters is not None: d["counters"] = counters
    publish_snapshot({"diagnostics": d})

def publish_connection(connected):
    publish_snapshot({"market": {"connected": bool(connected)}})

def publish_console_line(line):
    global _event_id
    line = line.rstrip("\r")
    if not line: return
    stripped = line.lstrip()
    level = "ERROR" if stripped.startswith(("ERROR", "CRITICAL", "Traceback", "Exception")) else (
        "WARNING" if stripped.startswith(("WARNING", "WARN")) else "INFO")
    with _lock:
        _event_id += 1
        _events.append({"id": _event_id, "time": _now(), "level": level, "message": line[:2000]})

def get_payload(after_event_id=0):
    with _lock:
        events = [deepcopy(e) for e in _events if e["id"] > after_event_id]
        return {"snapshot": deepcopy(_state), "events": events,
                "latest_event_id": _events[-1]["id"] if _events else after_event_id}

class ConsoleCapture:
    """Tee a stream to the terminal and dashboard event buffer."""
    def __init__(self, original):
        self.original = original
        self.buffer = ""
        self.lock = threading.Lock()
    def write(self, data):
        written = self.original.write(data)
        with self.lock:
            self.buffer += data
            while "\n" in self.buffer:
                line, self.buffer = self.buffer.split("\n", 1)
                publish_console_line(line)
        return written if written is not None else len(data)
    def flush(self): return self.original.flush()
    def isatty(self): return getattr(self.original, "isatty", lambda: False)()
    @property
    def encoding(self): return getattr(self.original, "encoding", "utf-8")

def install_console_capture():
    if not isinstance(sys.stdout, ConsoleCapture): sys.stdout = ConsoleCapture(sys.stdout)
    if not isinstance(sys.stderr, ConsoleCapture): sys.stderr = ConsoleCapture(sys.stderr)
