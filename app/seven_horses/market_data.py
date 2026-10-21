"""Read-only Zerodha Kite Connect market-data integration; no order functions."""
from __future__ import annotations
import argparse
import csv
import json
import logging
from datetime import datetime, timedelta
from typing import Any
from kiteconnect import KiteConnect, KiteTicker
from .config import Settings, settings

LOG = logging.getLogger("seven_horses.market_data")

class KiteMarketData:
    """Resolve seven NSE equities, download candles, and stream live quotes."""
    def __init__(self, config: Settings = settings) -> None:
        self.config = config
        self.kite: KiteConnect | None = None
        self.ticker: KiteTicker | None = None
        self.instruments: dict[str, dict[str, Any]] = {}

    def connect(self) -> KiteConnect:
        self.config.validate_credentials()
        self.kite = KiteConnect(api_key=self.config.api_key)
        self.kite.set_access_token(self.config.access_token)
        profile = self.kite.profile()  # Validate session; no trading action.
        LOG.info("Kite authenticated for user %s", profile.get("user_name", "unknown"))
        return self.kite

    def resolve_instruments(self) -> dict[str, dict[str, Any]]:
        """Resolve tokens dynamically from the current NSE instrument master."""
        kite = self.kite or self.connect()
        rows = kite.instruments(self.config.exchange)
        by_symbol = {
            row["tradingsymbol"]: row for row in rows
            if row.get("exchange") == self.config.exchange and row.get("instrument_type") == "EQ"
        }
        missing = [symbol for symbol in self.config.symbols if symbol not in by_symbol]
        if missing:
            raise RuntimeError("Symbols missing from NSE EQ instrument master: " + ", ".join(missing))
        self.instruments = {symbol: by_symbol[symbol] for symbol in self.config.symbols}
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.config.data_dir / "instrument_master.csv"
        fields = ["tradingsymbol", "instrument_token", "exchange", "instrument_type", "name"]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.instruments.values())
        LOG.info("Resolved %d instruments; saved %s", len(self.instruments), path)
        return self.instruments

    def download_history(self, days: int | None = None) -> dict[str, list[dict[str, Any]]]:
        """Download daily candles for swing research and save JSON per symbol."""
        kite = self.kite or self.connect()
        if not self.instruments:
            self.resolve_instruments()
        end = datetime.now()
        start = end - timedelta(days=days or self.config.history_days)
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        result: dict[str, list[dict[str, Any]]] = {}
        for symbol, instrument in self.instruments.items():
            candles = kite.historical_data(
                instrument_token=instrument["instrument_token"],
                from_date=start, to_date=end,
                interval=self.config.historical_interval,
                continuous=False, oi=False,
            )
            normalized = [{
                "timestamp": candle["date"].isoformat(),
                "open": float(candle["open"]), "high": float(candle["high"]),
                "low": float(candle["low"]), "close": float(candle["close"]),
                "volume": int(candle["volume"]),
            } for candle in candles]
            result[symbol] = normalized
            output = self.config.data_dir / (symbol.lower() + "_" + self.config.historical_interval + ".json")
            output.write_text(json.dumps(normalized, indent=2), encoding="utf-8")
            LOG.info("%s: saved %d candles to %s", symbol, len(normalized), output)
        return result

    def start_live_stream(self) -> None:
        """Append live quote ticks to JSONL for replay and later candle aggregation."""
        self.config.validate_credentials()
        if not self.instruments:
            self.resolve_instruments()
        self.config.data_dir.mkdir(parents=True, exist_ok=True)
        tick_path = self.config.data_dir / "live_ticks.jsonl"
        tokens = [int(row["instrument_token"]) for row in self.instruments.values()]
        token_to_symbol = {int(row["instrument_token"]): symbol for symbol, row in self.instruments.items()}
        self.ticker = KiteTicker(self.config.api_key, self.config.access_token)

        def on_connect(ws: Any, response: Any) -> None:
            ws.subscribe(tokens)
            ws.set_mode(ws.MODE_FULL, tokens)
            LOG.info("WebSocket connected; subscribed to %d symbols", len(tokens))

        def on_ticks(ws: Any, ticks: list[dict[str, Any]]) -> None:
            with tick_path.open("a", encoding="utf-8") as handle:
                for tick in ticks:
                    token = int(tick["instrument_token"])
                    record = {
                        "received_at": datetime.now().astimezone().isoformat(),
                        "symbol": token_to_symbol.get(token, "UNKNOWN"),
                        "instrument_token": token,
                        "last_price": tick.get("last_price"),
                        "last_traded_quantity": tick.get("last_traded_quantity"),
                        "volume": tick.get("volume_traded"),
                        "average_price": tick.get("average_traded_price"),
                        "ohlc": tick.get("ohlc"),
                        "exchange_timestamp": str(tick.get("exchange_timestamp") or ""),
                    }
                    handle.write(json.dumps(record, default=str) + "\n")
                    LOG.info("%s LTP=%s volume=%s", record["symbol"], record["last_price"], record["volume"])

        def on_error(ws: Any, code: int, reason: str) -> None:
            LOG.error("Kite WebSocket error %s: %s", code, reason)

        def on_close(ws: Any, code: int, reason: str) -> None:
            LOG.warning("Kite WebSocket closed %s: %s", code, reason)

        self.ticker.on_connect = on_connect
        self.ticker.on_ticks = on_ticks
        self.ticker.on_error = on_error
        self.ticker.on_close = on_close
        LOG.info("Starting read-only stream; writing ticks to %s", tick_path)
        self.ticker.connect(threaded=False)

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    parser = argparse.ArgumentParser(description="Seven Horses read-only market-data loader")
    parser.add_argument("command", choices=("check", "history", "stream"))
    parser.add_argument("--days", type=int, default=None, help="calendar days of history to download")
    args = parser.parse_args()
    client = KiteMarketData()
    client.connect()
    client.resolve_instruments()
    if args.command == "check":
        print("Kite authentication and all seven NSE instruments validated.")
        for symbol, row in client.instruments.items():
            print(f"{symbol}: token={row['instrument_token']} exchange={row['exchange']}")
    elif args.command == "history":
        data = client.download_history(days=args.days)
        print("Historical candles: " + ", ".join(f"{symbol}={len(rows)}" for symbol, rows in data.items()))
    else:
        client.start_live_stream()

if __name__ == "__main__":
    main()
