
from pathlib import Path

import pandas as pd

from app.config.settings import PROJECT_ROOT
from app.market.kite_client import create_kite_client

cache_dir = PROJECT_ROOT / "data"
cache_file = cache_dir / "nifty_options_instruments.csv"

print("Downloading NFO instruments from Kite...")
kite = create_kite_client()
instruments = kite.instruments("NFO")

df = pd.DataFrame(instruments)

nifty = df[
    (df["name"] == "NIFTY")
    & df["instrument_type"].isin(["CE", "PE"])
    ].copy()

columns = [
    "instrument_token",
    "tradingsymbol",
    "name",
    "expiry",
    "strike",
    "instrument_type",
]

nifty = nifty[columns]

if nifty.empty:
    raise RuntimeError("No NIFTY option contracts found.")

cache_dir.mkdir(parents=True, exist_ok=True)
nifty.to_csv(cache_file, index=False)

print(f"Saved {len(nifty)} NIFTY option contracts.")
print(f"Cache file: {cache_file.resolve()}")
