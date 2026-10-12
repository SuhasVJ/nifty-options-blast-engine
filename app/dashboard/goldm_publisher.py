"""Independent thread-safe GOLDM dashboard state and console capture."""
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
    "goldm": {
        "connected": False, "future_symbol": None, "future_ltp": None,
        "future_expiry": None, "option_expiry": None, "options": [],
        "tracked_count": 0, "last_tick_time": None,
        "message": "GOLDM scanner not started",
        "scoring_status": "SHADOW MODE: experimental scores only; not calibrated",
    },
}

def _now():
    return datetime.now(ZoneInfo("Asia/Kolkata")).isoformat(timespec="seconds")

def publish_goldm(payload):
    with _lock:
        _state["goldm"].update(deepcopy(payload))
        _state["updated_at"] = _now()

def publish_console_line(line):
    global _event_id
    line = line.rstrip("\r")
    if not line:
        return
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
    def flush(self):
        return self.original.flush()
    def isatty(self):
        return getattr(self.original, "isatty", lambda: False)()
    @property
    def encoding(self):
        return getattr(self.original, "encoding", "utf-8")

def install_console_capture():
    if not isinstance(sys.stdout, ConsoleCapture):
        sys.stdout = ConsoleCapture(sys.stdout)
    if not isinstance(sys.stderr, ConsoleCapture):
        sys.stderr = ConsoleCapture(sys.stderr)
