"""Standalone GOLDM futures/options monitor. Monitoring only; no order placement."""
import time
from app.dashboard.goldm_publisher import install_console_capture
from app.dashboard.goldm_server import start_dashboard
from app.commodities.goldm_scanner import start_goldm_scanner

def main():
    install_console_capture()
    start_dashboard(host="127.0.0.1", port=8766)
    print("GOLDM dashboard available at http://127.0.0.1:8766")
    print("Starting standalone GOLDM futures/options monitor (monitoring only)...")
    start_goldm_scanner()
    # Keep the process alive; scanner and dashboard servers run in daemon threads.
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("GOLDM monitor stopped by user.")

if __name__ == "__main__":
    main()
