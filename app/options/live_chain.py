from kiteconnect import KiteTicker

from app.config.settings import KITE_API_KEY, KITE_ACCESS_TOKEN
from app.options.instruments import get_nifty_instruments
from app.options.chain import (
    get_nearest_expiry,
    get_atm_strike,
    get_option_chain,
)
from app.options.state_manager import OptionStateManager
from app.options.greeks_service import GreeksService


NIFTY_50_TOKEN = 256265

state_manager = OptionStateManager()
greeks_service = GreeksService(
    risk_free_rate=0.06,
    dividend_yield=0.0,
)

# Loaded once before WebSocket startup.
instrument_df = None

current_nifty_price = 0.0
current_atm = None
current_expiry = None

subscribed_option_tokens = set()
instrument_metadata = {}


def subscribe_options_if_needed(ws, nifty_price):
    global current_atm, current_expiry
    global subscribed_option_tokens, instrument_metadata

    if instrument_df is None:
        print("ERROR: Instrument master is not loaded.")
        return

    # Cheap check using the cached DataFrame.
    expiry = get_nearest_expiry(instrument_df)

    expiry_df = instrument_df[
        instrument_df["expiry"] == expiry
        ]

    strikes = sorted(expiry_df["strike"].unique())
    atm = get_atm_strike(nifty_price, strikes)

    # Avoid rebuilding the chain on every NIFTY tick.
    if (
            current_atm == atm
            and current_expiry == expiry
            and subscribed_option_tokens
    ):
        return

    # Build the chain only when ATM or expiry changes.
    chain, expiry, atm = get_option_chain(
        nifty_price,
        instruments_df=instrument_df,
    )

    new_metadata = {
        int(row.instrument_token): {
            "tradingsymbol": row.tradingsymbol,
            "strike": float(row.strike),
            "expiry": row.expiry,
            "option_type": row.instrument_type,
        }
        for _, row in chain.iterrows()
    }

    new_tokens = set(new_metadata.keys())

    tokens_to_unsubscribe = (
            subscribed_option_tokens - new_tokens
    )
    tokens_to_subscribe = (
            new_tokens - subscribed_option_tokens
    )

    if tokens_to_unsubscribe:
        ws.unsubscribe(list(tokens_to_unsubscribe))

    if tokens_to_subscribe:
        tokens = list(tokens_to_subscribe)
        ws.subscribe(tokens)
        ws.set_mode(ws.MODE_FULL, tokens)

    instrument_metadata = new_metadata
    subscribed_option_tokens = new_tokens
    current_atm = atm
    current_expiry = expiry

    print("\n========================================")
    print("OPTIONS SUBSCRIBED")
    print("========================================")
    print(f"Expiry: {expiry}")
    print(f"ATM: {atm}")
    print(f"Added: {len(tokens_to_subscribe)}")
    print(f"Removed: {len(tokens_to_unsubscribe)}")
    print(f"Total subscribed: {len(new_tokens)}")
    print("========================================\n")


def on_connect(ws, response):
    print("WebSocket connected successfully")

    ws.subscribe([NIFTY_50_TOKEN])
    ws.set_mode(ws.MODE_FULL, [NIFTY_50_TOKEN])

    print("Subscribed to NIFTY 50")


def on_ticks(ws, ticks):
    global current_nifty_price

    for tick in ticks:
        try:
            token = tick.get("instrument_token")

            if not token:
                continue

            if token == NIFTY_50_TOKEN:
                price = tick.get("last_price")

                if not price:
                    continue

                current_nifty_price = float(price)
                state_manager.update_nifty(tick)

                print(f"\nNIFTY = {current_nifty_price:.2f}")

                try:
                    subscribe_options_if_needed(
                        ws,
                        current_nifty_price,
                    )
                except Exception as exc:
                    # Keep one bad chain update from crashing
                    # the WebSocket callback.
                    print(
                        "Option-chain update failed: "
                        f"{type(exc).__name__}: {exc}"
                    )

                continue

            metadata = instrument_metadata.get(token)

            if metadata is None:
                continue

            state = state_manager.update(tick)
            ltp = state.last_price

            if ltp <= 0 or current_nifty_price <= 0:
                continue

            greeks = greeks_service.calculate(
                spot=current_nifty_price,
                strike=metadata["strike"],
                option_price=ltp,
                option_type=metadata["option_type"],
                expiry_date=metadata["expiry"],
            )

            if greeks is None:
                continue

            price_5s = state.price_change_pct(5)
            price_30s = state.price_change_pct(30)
            price_60s = state.price_change_pct(60)

            oi_30s = state.oi_change_pct(30)
            volume_30s = state.volume_change(30)
            volume_acceleration = state.volume_acceleration()

            nifty_30s = (
                state_manager
                .get_nifty()
                .price_change_pct(30)
            )

            print(
                f"OPTION | {metadata['tradingsymbol']} | "
                f"LTP={ltp:.2f} | "
                f"OI={state.oi:,} | "
                f"Volume={state.volume:,} | "
                f"IV={greeks['iv'] * 100:.2f}% | "
                f"Delta={greeks['delta']:+.4f} | "
                f"Gamma={greeks['gamma']:.6f} | "
                f"Vega={greeks['vega']:.2f} | "
                f"Theta={greeks['theta']:.2f} | "
                f"P5s={price_5s:+.2f}% | "
                f"P30s={price_30s:+.2f}% | "
                f"P60s={price_60s:+.2f}% | "
                f"OI30s={oi_30s:+.2f}% | "
                f"Vol30s={volume_30s:,} | "
                f"VolAccel={volume_acceleration:.2f} | "
                f"NIFTY30s={nifty_30s:+.2f}%"
            )

        except Exception as exc:
            print(
                f"Tick processing error: "
                f"{type(exc).__name__}: {exc}"
            )


def on_error(ws, code, reason):
    print(f"WebSocket error: code={code}, reason={reason}")


def on_close(ws, code, reason):
    print(f"WebSocket closed: code={code}, reason={reason}")


def on_reconnect(ws, attempts_count):
    print(f"WebSocket reconnect attempt: {attempts_count}")


def on_noreconnect(ws, attempts_count):
    print(
        f"WebSocket stopped reconnecting after "
        f"{attempts_count} attempts"
    )


def main():
    global instrument_df

    print("\nStarting NIFTY Options Blast Engine...")

    if not KITE_API_KEY or not KITE_ACCESS_TOKEN:
        raise ValueError(
            "Kite API key or access token is missing. "
            "Check your .env configuration."
        )

    # Critical: download instruments before starting WebSocket.
    # A REST failure here stops startup instead of creating a
    # reconnect-and-fail loop inside on_ticks().
    try:
        instrument_df = get_nifty_instruments()
        print(
            f"Instrument cache ready: "
            f"{len(instrument_df)} NIFTY contracts"
        )
    except Exception as exc:
        print(
            "Could not load NIFTY instruments. "
            "WebSocket was not started. "
            f"{type(exc).__name__}: {exc}"
        )
        return

    kws = KiteTicker(KITE_API_KEY, KITE_ACCESS_TOKEN)

    kws.on_connect = on_connect
    kws.on_ticks = on_ticks
    kws.on_error = on_error
    kws.on_close = on_close
    kws.on_reconnect = on_reconnect
    kws.on_noreconnect = on_noreconnect

    kws.connect()


if __name__ == "__main__":
    main()