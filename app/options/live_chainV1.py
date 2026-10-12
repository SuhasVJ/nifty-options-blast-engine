import threading
import time
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

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
from app.options.blast_score import BlastScoreEngine
from app.options.tick_validation import is_valid_price

from app.dashboard.publisher import (
    install_console_capture,
    publish_connection,
    publish_diagnostics,
    publish_report,
    publish_snapshot,
)
from app.dashboard.server import start_dashboard

IST = ZoneInfo("Asia/Kolkata")
NIFTY_50_TOKEN = 256265

REPORT_INTERVAL_SECONDS = 10
CANDIDATE_MAX_AGE_SECONDS = 30
TOP_CANDIDATES = 3

state_manager = OptionStateManager()

greeks_service = GreeksService(
    risk_free_rate=0.06,
    dividend_yield=0.0,
)

score_engine = BlastScoreEngine()

instrument_df = None

current_nifty_price = 0.0
current_atm = None
current_expiry = None

subscribed_option_tokens = set()
instrument_metadata = {}

# token -> latest score record and local monotonic update time
latest_scores = {}
candidate_lock = threading.RLock()

last_report_time = 0.0
last_warmup_message_time = 0.0
last_diagnostic_time = 0.0

DIAGNOSTIC_INTERVAL_SECONDS = 30

diagnostic_counts = Counter()
diagnostic_statuses = Counter()
# Counts FILTERED scoring outcomes by CE/PE tick evaluations.
diagnostic_filtered_by_type = Counter()

# True only after the option universe is successfully reconciled.
option_universe_synced = False

def reset_subscription_state():
    global current_atm, current_expiry, option_universe_synced

    current_atm = None
    current_expiry = None
    option_universe_synced = False

    subscribed_option_tokens.clear()
    instrument_metadata.clear()

def invalidate_option_universe():
    """Block scoring until the option universe is reconciled."""
    global instrument_metadata, option_universe_synced

    instrument_metadata = {}
    option_universe_synced = False

    with candidate_lock:
        latest_scores.clear()

def _get_client_subscription_modes(ws):
    """Return the SDK's local token-to-mode view."""
    modes = getattr(ws, "subscribed_tokens", None)

    if isinstance(modes, dict):
        return dict(modes)

    # Compatibility for simple mocked WebSocket objects in tests.
    # Real KiteTicker instances expose subscribed_tokens.
    full_mode = getattr(ws, "MODE_FULL", "full")
    return {
        token: full_mode
        for token in subscribed_option_tokens
    }


def subscribe_options_if_needed(ws, nifty_price):
    global current_atm, current_expiry
    global subscribed_option_tokens, instrument_metadata
    global option_universe_synced

    if instrument_df is None:
        print("ERROR: Instrument master is not loaded.")
        invalidate_option_universe()
        return

    expiry = get_nearest_expiry(instrument_df)
    expiry_df = instrument_df[instrument_df["expiry"] == expiry]

    strikes = sorted(expiry_df["strike"].unique())
    atm = get_atm_strike(nifty_price, strikes)

    if (
            option_universe_synced
            and current_atm == atm
            and current_expiry == expiry
            and subscribed_option_tokens
    ):
        return

    chain, expiry, atm = get_option_chain(
        nifty_price,
        instruments_df=instrument_df,
    )

    if chain is None or chain.empty:
        print("WARNING: Option chain is empty; invalidating old candidates.")
        invalidate_option_universe()
        return

    new_metadata = {
        int(row.instrument_token): {
            "tradingsymbol": row.tradingsymbol,
            "strike": float(row.strike),
            "expiry": row.expiry,
            "option_type": row.instrument_type,
        }
        for _, row in chain.iterrows()
    }

    new_tokens = set(new_metadata)

    # Fail closed during reconciliation. If an operation raises,
    # old metadata and candidates cannot be used for scoring.
    invalidate_option_universe()

    client_modes = _get_client_subscription_modes(ws)
    current_option_tokens = set(client_modes) - {NIFTY_50_TOKEN}

    tokens_to_unsubscribe = current_option_tokens - new_tokens
    tokens_to_subscribe = new_tokens - current_option_tokens

    # Remove obsolete options first.
    if tokens_to_unsubscribe:
        ws.unsubscribe(list(tokens_to_unsubscribe))
        for token in tokens_to_unsubscribe:
            client_modes.pop(token, None)

    # Add options missing from the SDK's local subscription map.
    if tokens_to_subscribe:
        ws.subscribe(list(tokens_to_subscribe))

        quote_mode = getattr(ws, "MODE_QUOTE", "quote")
        for token in tokens_to_subscribe:
            client_modes[token] = quote_mode

    # Ensure every desired option is in full mode, including tokens
    # subscribed successfully before a previous set_mode failure.
    full_mode = ws.MODE_FULL
    tokens_needing_full_mode = [
        token
        for token in new_tokens
        if client_modes.get(token) != full_mode
    ]

    if tokens_needing_full_mode:
        ws.set_mode(full_mode, tokens_needing_full_mode)

    # Commit local state only after every required operation succeeds.
    instrument_metadata = new_metadata
    subscribed_option_tokens = new_tokens
    current_atm = atm
    current_expiry = expiry
    option_universe_synced = True

    with candidate_lock:
        for token in list(latest_scores):
            if token not in new_tokens:
                latest_scores.pop(token, None)

    print("\n========================================")
    print("OPTIONS SUBSCRIBED")
    print("========================================")
    print(f"Expiry: {expiry}")
    print(f"ATM: {atm}")
    print(f"Added: {len(tokens_to_subscribe)}")
    print(f"Removed: {len(tokens_to_unsubscribe)}")
    print(f"Total tracked: {len(new_tokens)}")
    print("Synchronization: local requests completed")
    print("========================================\n")



def process_option_tick(tick, metadata):
    diagnostic_counts["option_ticks_received"] += 1

    if not option_universe_synced:
        diagnostic_counts["skipped_universe_not_synced"] += 1
        return

    token = int(tick["instrument_token"])
    raw_ltp = tick.get("last_price")

    if not is_valid_price(raw_ltp):
        diagnostic_counts["invalid_option_prices"] += 1
        return

    if not is_valid_price(current_nifty_price):
        diagnostic_counts["invalid_nifty_prices"] += 1
        return

    state = state_manager.update(tick)

    if state is None:
        diagnostic_counts["invalid_option_state_updates"] += 1
        return

    ltp = state.last_price

    if not is_valid_price(ltp):
        diagnostic_counts["invalid_state_prices"] += 1
        return

    # Check option and underlying history readiness.
    nifty_state = state_manager.get_nifty()

    has_5s = state.has_history(5)
    has_30s = state.has_history(30)
    has_60s = state.has_history(60)
    nifty_has_30s = nifty_state.has_history(30)

    if not has_5s:
        diagnostic_counts["missing_option_5s_history"] += 1

    if not has_30s:
        diagnostic_counts["missing_option_30s_history"] += 1

    if not has_60s:
        diagnostic_counts["missing_option_60s_history"] += 1

    if not nifty_has_30s:
        diagnostic_counts["missing_nifty_30s_history"] += 1

    data_ready = (
            has_5s
            and has_30s
            and has_60s
            and nifty_has_30s
    )

    if not data_ready:
        diagnostic_counts["insufficient_history"] += 1

    # Calculate Greeks.
    greeks = greeks_service.calculate(
        spot=current_nifty_price,
        strike=metadata["strike"],
        option_price=ltp,
        option_type=metadata["option_type"],
        expiry_date=metadata["expiry"],
    )

    if greeks is None:
        diagnostic_counts["greeks_failed"] += 1

        with candidate_lock:
            latest_scores.pop(token, None)

        return

    # Print only the first 10 successful Greek calculations.
    if diagnostic_counts["greeks_samples"] < 10:
        diagnostic_counts["greeks_samples"] += 1

        print(
            "GREEKS SAMPLE | "
            f"{metadata['tradingsymbol']} | "
            f"LTP={ltp:.2f} | "
            f"IV={greeks['iv'] * 100:.2f}% | "
            f"Delta={greeks['delta']:+.4f} | "
            f"Gamma={greeks['gamma']:.7f}"
        )

    # Count eligibility filters only when market history is ready.
    # These checks do not change the existing scoring rules.
    if data_ready:
        delta = abs(greeks.get("delta", 0))
        iv = greeks.get("iv", 0)
        gamma = greeks.get("gamma", 0)

        if delta <= 0.30:
            diagnostic_counts["filter_delta"] += 1

        if not (0 < iv < 0.15):
            diagnostic_counts["filter_iv"] += 1

        if gamma <= 0.0012:
            diagnostic_counts["filter_gamma"] += 1

        if (
                delta > 0.30
                and 0 < iv < 0.15
                and gamma > 0.0012
        ):
            diagnostic_counts["passed_all_filters"] += 1

    # Calculate market movement and activity features.
    price_5s = state.price_change_pct(5)
    price_30s = state.price_change_pct(30)
    oi_30s = state.oi_change_pct(30)
    volume_30s = state.volume_change(30)
    volume_acceleration = state.volume_acceleration()
    nifty_30s = nifty_state.price_change_pct(30)

    result = score_engine.calculate(
        option_type=metadata["option_type"],
        greeks=greeks,
        price_change_5s=price_5s,
        price_change_30s=price_30s,
        oi_change_pct_30s=oi_30s,
        volume_change_30s=volume_30s,
        volume_acceleration=volume_acceleration,
        nifty_change_pct_30s=nifty_30s,
        data_ready=data_ready,
    )

    if result["score"] is None:
        diagnostic_counts["score_rejected"] += 1
        result_status = str(result.get("status", "UNKNOWN"))
        diagnostic_statuses[result_status] += 1

        if result_status == "FILTERED":
            diagnostic_filtered_by_type[metadata["option_type"]] += 1

        with candidate_lock:
            latest_scores.pop(token, None)

        return

    diagnostic_counts["successful_scores"] += 1
    diagnostic_statuses[
        str(result.get("status", "UNKNOWN"))
    ] += 1

    # Publish the latest score for this option.
    with candidate_lock:
        latest_scores[token] = {
            "updated_at": time.monotonic(),
            "tradingsymbol": metadata["tradingsymbol"],
            "option_type": metadata["option_type"],
            "ltp": ltp,
            "iv": greeks["iv"] * 100,
            "delta": greeks["delta"],
            "gamma": greeks["gamma"],
            "price_change_30s": price_30s,
            "oi_change_30s": oi_30s,
            "volume_change_30s": volume_30s,
            "nifty_change_30s": nifty_30s,
            "score": result["score"],
            "status": result["status"],
        }


def cleanup_stale_candidates():
    """Remove stale candidates safely while other threads update scores."""
    now = time.monotonic()
    removed = 0

    with candidate_lock:
        for token, candidate in list(latest_scores.items()):
            if (
                    now - candidate["updated_at"]
                    > CANDIDATE_MAX_AGE_SECONDS
            ):
                # Do not remove a newer replacement for this token.
                if latest_scores.get(token) is candidate:
                    latest_scores.pop(token, None)
                    removed += 1

    return removed




def print_candidate_report():
    # Remove stale candidates using the thread-safe cleanup function.
    cleanup_stale_candidates()

    # Take a consistent snapshot while holding the lock.
    with candidate_lock:
        candidates_snapshot = list(latest_scores.values())

    publish_report(
        candidates=candidates_snapshot,
        nifty=current_nifty_price,
        expiry=current_expiry,
        atm=current_atm,
    )

    print("\n" + "=" * 76)
    print(
        f"BLAST SCORE REPORT | "
        f"{datetime.now(IST).strftime('%H:%M:%S')} IST"
    )
    print(f"NIFTY: {current_nifty_price:.2f}")
    print(f"Expiry: {current_expiry} | ATM: {current_atm}")
    print("=" * 76)

    for option_type, heading in (
            ("CE", "TOP BULLISH CANDIDATES (CE)"),
            ("PE", "TOP BEARISH CANDIDATES (PE)"),
    ):
        candidates = [
            candidate
            for candidate in candidates_snapshot
            if candidate["option_type"] == option_type
        ]

        candidates.sort(
            key=lambda candidate: candidate["score"],
            reverse=True,
        )

        print(f"\n{heading}")

        if not candidates:
            print("No eligible candidates yet.")
            continue

        for rank, candidate in enumerate(
                candidates[:TOP_CANDIDATES],
                start=1,
        ):
            print(
                f"{rank}. {candidate['tradingsymbol']} | "
                f"Score={candidate['score']:.1f}/100 | "
                f"{candidate['status']} | "
                f"LTP={candidate['ltp']:.2f} | "
                f"IV={candidate['iv']:.2f}% | "
                f"Delta={candidate['delta']:+.3f} | "
                f"Gamma={candidate['gamma']:.6f} | "
                f"P30s={candidate['price_change_30s']:+.2f}% | "
                f"OI30s={candidate['oi_change_30s']:+.2f}% | "
                f"NIFTY30s={candidate['nifty_change_30s']:+.2f}%"
            )

    print("\nScores are screening indicators, not trade instructions.")
    print("=" * 76)



def on_connect(ws, response):
    global current_nifty_price
    global last_report_time, last_warmup_message_time
    global option_universe_synced

    # Reset historical market data from the previous connection.
    state_manager.reset()

    # Clear previously ranked candidates safely.
    with candidate_lock:
        latest_scores.clear()

    # Reset local subscription tracking.
    reset_subscription_state()

    current_nifty_price = 0.0
    last_report_time = 0.0
    last_warmup_message_time = 0.0

    publish_connection(True)
    publish_snapshot({"market": {"last_tick_time": None}})

    print("WebSocket connected successfully")
    print("Previous market history and candidates cleared.")

    ws.subscribe([NIFTY_50_TOKEN])
    ws.set_mode(ws.MODE_FULL, [NIFTY_50_TOKEN])

    print("Subscribed to NIFTY 50")
    print("Waiting for fresh market history to accumulate...")



def on_ticks(ws, ticks):
    global current_nifty_price
    global last_report_time, last_warmup_message_time
    global last_diagnostic_time

    publish_snapshot({
        "market": {
            "last_tick_time": datetime.now(IST).strftime("%H:%M:%S IST"),
        }
    })

    for tick in ticks:
        try:
            token = tick.get("instrument_token")

            if token is None:
                continue

            token = int(token)

            if token == NIFTY_50_TOKEN:
                price = tick.get("last_price")

                if not is_valid_price(price):
                    print(
                        f"WARNING: Ignoring invalid NIFTY price: {price!r}"
                    )
                    continue

                nifty_state = state_manager.update_nifty(tick)

                if nifty_state is None:
                    print(
                        "WARNING: Ignoring invalid or out-of-order NIFTY tick."
                    )
                    continue

                current_nifty_price = nifty_state.last_price

                try:
                    subscribe_options_if_needed(
                        ws,
                        current_nifty_price,
                    )
                except Exception as exc:
                    invalidate_option_universe()
                    print(
                        "Option-chain update failed; old candidates invalidated: "
                        f"{type(exc).__name__}: {exc}"
                    )

                continue

            metadata = instrument_metadata.get(token)

            if metadata is None:
                continue

            process_option_tick(tick, metadata)

        except Exception as exc:
            print(
                f"Tick processing error: "
                f"{type(exc).__name__}: {exc}"
            )

    now = time.monotonic()

    # Print diagnostic counters every 30 seconds.
    if now - last_diagnostic_time >= DIAGNOSTIC_INTERVAL_SECONDS:
        last_diagnostic_time = now

        print("\n--- BLAST SCORE DIAGNOSTICS ---")
        print(
            f"Option ticks received: "
            f"{diagnostic_counts['option_ticks_received']}"
        )
        print(
            f"Universe not synced: "
            f"{diagnostic_counts['skipped_universe_not_synced']}"
        )
        print(
            f"Missing option 5s history: "
            f"{diagnostic_counts['missing_option_5s_history']}"
        )
        print(
            f"Missing option 30s history: "
            f"{diagnostic_counts['missing_option_30s_history']}"
        )
        print(
            f"Missing option 60s history: "
            f"{diagnostic_counts['missing_option_60s_history']}"
        )
        print(
            f"Missing NIFTY 30s history: "
            f"{diagnostic_counts['missing_nifty_30s_history']}"
        )
        print(
            f"Insufficient history: "
            f"{diagnostic_counts['insufficient_history']}"
        )
        print(
            f"Greeks failures: "
            f"{diagnostic_counts['greeks_failed']}"
        )
        print(
            f"Rejected scores: "
            f"{diagnostic_counts['score_rejected']}"
        )
        print(f"Delta filter rejections: {diagnostic_counts['filter_delta']}")
        print(f"IV filter rejections: {diagnostic_counts['filter_iv']}")
        print(f"Gamma filter rejections: {diagnostic_counts['filter_gamma']}")
        print(f"Passed all filters: {diagnostic_counts['passed_all_filters']}")
        print(
            f"Successful scores: "
            f"{diagnostic_counts['successful_scores']}"
        )
        print(f"Scoring statuses: {dict(diagnostic_statuses)}")
        print(
            "FILTERED by option type (tick evaluations): "
            f"CE={diagnostic_filtered_by_type['CE']} | "
            f"PE={diagnostic_filtered_by_type['PE']}"
        )
        publish_diagnostics(
            statuses=dict(diagnostic_statuses),
            filtered_by_type=dict(diagnostic_filtered_by_type),
            counters=dict(diagnostic_counts),
        )
        print("-------------------------------")

    # Print candidate reports or the existing warm-up message.
    if now - last_report_time >= REPORT_INTERVAL_SECONDS:
        last_report_time = now

        with candidate_lock:
            has_candidates = bool(latest_scores)

        if has_candidates:
            print_candidate_report()
        elif now - last_warmup_message_time >= 30:
            last_warmup_message_time = now
            print(
                "Blast Score warming up: waiting for sufficient "
                "recent option and NIFTY history."
            )


def on_error(ws, code, reason):
    print(f"WebSocket error: code={code}, reason={reason}")


def on_close(ws, code, reason):
    publish_connection(False)
    print(f"WebSocket closed: code={code}, reason={reason}")



def on_reconnect(ws, attempts_count):
    print(
        f"WebSocket reconnect attempt: {attempts_count}"
    )


def on_noreconnect(ws):
    publish_connection(False)
    print(
        "CRITICAL: WebSocket reconnection attempts exhausted. "
        "Scanner may no longer receive live updates. "
        "Check connectivity and restart the scanner if necessary."
    )



def stale_candidate_cleanup_loop(stop_event=None):
    """Remove stale candidates periodically, even without incoming ticks."""
    interval = max(
        1.0,
        min(5.0, CANDIDATE_MAX_AGE_SECONDS / 2),
    )

    while stop_event is None or not stop_event.is_set():
        if stop_event is None:
            time.sleep(interval)
        elif stop_event.wait(interval):
            break

        try:
            cleanup_stale_candidates()
        except Exception as exc:
            print(
                "Stale candidate cleanup error: "
                f"{type(exc).__name__}: {exc}"
            )


def main():
    global instrument_df

    install_console_capture()
    start_dashboard(host="127.0.0.1", port=8765)
    print("Dashboard available at http://127.0.0.1:8765")
    print("\nStarting NIFTY Options Blast Engine...")

    if not KITE_API_KEY or not KITE_ACCESS_TOKEN:
        raise ValueError(
            "Kite API key or access token is missing. "
            "Check your .env configuration."
        )

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

    threading.Thread(
        target=stale_candidate_cleanup_loop,
        name="stale-candidate-cleanup",
        daemon=True,
    ).start()

    kws.connect()


if __name__ == "__main__":
    main()
