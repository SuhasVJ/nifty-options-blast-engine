from kiteconnect import KiteTicker

from app.config.settings import KITE_API_KEY, KITE_ACCESS_TOKEN


NIFTY_50_TOKEN = 256265


def on_connect(ws, response):
    print("WebSocket connected successfully")

    ws.subscribe([NIFTY_50_TOKEN])
    ws.set_mode(ws.MODE_FULL, [NIFTY_50_TOKEN])

    print("Subscribed to NIFTY 50")


def on_ticks(ws, ticks):
    print("\nReceived tick:")

    for tick in ticks:
        print(tick)


def on_close(ws, code, reason):
    print(f"WebSocket closed: {code} - {reason}")


def on_error(ws, code, reason):
    print(f"WebSocket error: {code} - {reason}")


def on_reconnect(ws, attempts_count):
    print(f"Reconnecting... attempt {attempts_count}")


def on_noreconnect(ws):
    print("Maximum reconnect attempts reached")


if __name__ == "__main__":

    print("API key loaded:", bool(KITE_API_KEY))
    print("Access token loaded:", bool(KITE_ACCESS_TOKEN))

    kws = KiteTicker(
        KITE_API_KEY,
        KITE_ACCESS_TOKEN
    )

    kws.on_connect = on_connect
    kws.on_ticks = on_ticks
    kws.on_close = on_close
    kws.on_error = on_error
    kws.on_reconnect = on_reconnect
    kws.on_noreconnect = on_noreconnect

    print("Connecting to Kite WebSocket...")

    kws.connect()