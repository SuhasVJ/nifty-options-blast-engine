from datetime import date

from app.options.instruments import get_nifty_instruments


STRIKE_RANGE = 10


def get_nearest_expiry(df):
    today = date.today()

    expiries = sorted(
        expiry
        for expiry in df["expiry"].unique()
        if expiry >= today
    )

    if not expiries:
        raise ValueError("No future NIFTY expiry found")

    return expiries[0]


def get_atm_strike(nifty_price, strikes):
    if len(strikes) == 0:
        raise ValueError("No strikes available")

    return min(
        strikes,
        key=lambda strike: abs(float(strike) - nifty_price)
    )


def get_option_chain(nifty_price, instruments_df=None):
    # Use the supplied cache, or load the cached instruments.
    df = (
        instruments_df
        if instruments_df is not None
        else get_nifty_instruments()
    )

    expiry = get_nearest_expiry(df)

    expiry_df = df[df["expiry"] == expiry].copy()

    strikes = sorted(expiry_df["strike"].unique())
    atm_strike = get_atm_strike(nifty_price, strikes)

    atm_index = strikes.index(atm_strike)

    start = max(0, atm_index - STRIKE_RANGE)
    end = min(len(strikes), atm_index + STRIKE_RANGE + 1)

    selected_strikes = strikes[start:end]

    chain = expiry_df[
        expiry_df["strike"].isin(selected_strikes)
    ].copy()

    return chain, expiry, atm_strike


if __name__ == "__main__":
    nifty_price = 22231.80

    chain, expiry, atm = get_option_chain(nifty_price)

    print("\n========== NIFTY OPTION CHAIN ==========")
    print("NIFTY:", nifty_price)
    print("Expiry:", expiry)
    print("ATM:", atm)
    print(
        chain[
            [
                "instrument_token",
                "tradingsymbol",
                "strike",
                "instrument_type",
            ]
        ]
        .sort_values(["strike", "instrument_type"])
        .to_string(index=False)
    )