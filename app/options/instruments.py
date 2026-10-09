
from datetime import date
from functools import lru_cache
from pathlib import Path

import pandas as pd

from app.config.settings import PROJECT_ROOT
from app.market.kite_client import create_kite_client

CACHE_DIR = PROJECT_ROOT / "data"
CACHE_FILE = CACHE_DIR / "nifty_options_instruments.csv"

OPTION_COLUMNS = [
    "instrument_token",
    "tradingsymbol",
    "name",
    "expiry",
    "strike",
    "instrument_type",
]


def _read_cache():
    df = pd.read_csv(CACHE_FILE)
    df["expiry"] = pd.to_datetime(df["expiry"]).dt.date
    return df


@lru_cache(maxsize=1)
def get_nifty_instruments():
    # Reuse today's cache without calling Kite.
    if CACHE_FILE.exists():
        cache_date = date.fromtimestamp(CACHE_FILE.stat().st_mtime)

        if cache_date == date.today():
            print(f"Loading NIFTY instruments from local cache: {CACHE_FILE}")
            return _read_cache()

    try:
        print("Downloading NFO instruments from Kite...")
        kite = create_kite_client()
        instruments = kite.instruments("NFO")
        df = pd.DataFrame(instruments)

        nifty_options = df[
            (df["name"] == "NIFTY")
            & df["instrument_type"].isin(["CE", "PE"])
            ][OPTION_COLUMNS].copy()

        if nifty_options.empty:
            raise ValueError("No NIFTY option contracts returned by Kite")

        nifty_options["expiry"] = pd.to_datetime(
            nifty_options["expiry"]
        ).dt.date

        CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Store dates in a format pandas can reload reliably.
        nifty_options.to_csv(CACHE_FILE, index=False)

        print(f"Cached {len(nifty_options)} NIFTY option contracts")
        print(f"Local cache saved: {CACHE_FILE}")

        return nifty_options

    except Exception as exc:
        # A previous cache can still be used if Kite is unavailable.
        if CACHE_FILE.exists():
            print(f"Kite download failed: {exc}")
            print("Using the existing local cache instead.")
            return _read_cache()

        raise
