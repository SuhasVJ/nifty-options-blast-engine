from kiteconnect import KiteConnect

from app.config.settings import KITE_API_KEY, KITE_ACCESS_TOKEN


def create_kite_client():
    if not KITE_API_KEY:
        raise ValueError("KITE_API_KEY is missing")

    if not KITE_ACCESS_TOKEN:
        raise ValueError("KITE_ACCESS_TOKEN is missing")

    return KiteConnect(
        api_key=KITE_API_KEY,
        access_token=KITE_ACCESS_TOKEN
    )


if __name__ == "__main__":
    kite = create_kite_client()

    print("Testing Kite REST API...")

    profile = kite.profile()

    print("REST API successful")
    print("User ID:", profile["user_id"])
    print("User Name:", profile["user_name"])