"""Start the local MCX Natural Gas signal monitor (no orders)."""
import time

from app.commodities.natural_gas_scanner import start_natural_gas_scanner
from app.dashboard.natural_gas_server import start_dashboard


def main():
    start_dashboard(host="127.0.0.1", port=8767)
    print("Natural Gas signals dashboard: http://127.0.0.1:8767")
    print("Starting MCX Natural Gas futures scanner (signals only; no orders)...")
    scanner = start_natural_gas_scanner()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        scanner.stop()
        print("Natural Gas scanner stopped.")


if __name__ == "__main__":
    main()
