"""Configuration for the Seven Horses market-data engine."""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("KITE_API_KEY", "")
    access_token: str = os.getenv("KITE_ACCESS_TOKEN", "")
    exchange: str = os.getenv("SEVEN_HORSES_EXCHANGE", "NSE")
    symbols: tuple[str, ...] = ("RELIANCE", "HDFCBANK", "ICICIBANK", "SBIN", "INFY", "TECHM", "HCLTECH")
    data_dir: Path = Path(os.getenv("SEVEN_HORSES_DATA_DIR", str(ROOT / "data" / "seven_horses")))
    historical_interval: str = os.getenv("SEVEN_HORSES_INTERVAL", "day")
    history_days: int = int(os.getenv("SEVEN_HORSES_HISTORY_DAYS", "730"))

    def validate_credentials(self) -> None:
        missing = []
        if not self.api_key:
            missing.append("KITE_API_KEY")
        if not self.access_token:
            missing.append("KITE_ACCESS_TOKEN")
        if missing:
            raise RuntimeError("Missing Kite credentials in repository-root .env: " + ", ".join(missing)
                               + ". Create or refresh a Kite session before running.")

settings = Settings()
