from kiteconnect import KiteConnect

from app.config.settings import KITE_API_KEY, KITE_API_SECRET
from pathlib import Path

def update_access_token(access_token: str):
    env_file = Path(__file__).resolve().parents[2] / ".env"

    lines = env_file.read_text().splitlines()

    updated = False

    for i, line in enumerate(lines):
        if line.startswith("KITE_ACCESS_TOKEN="):
            lines[i] = f"KITE_ACCESS_TOKEN={access_token}"
            updated = True
            break

    if not updated:
        lines.append(f"KITE_ACCESS_TOKEN={access_token}")

    env_file.write_text("\n".join(lines) + "\n")

def create_kite_client():
    return KiteConnect(api_key=KITE_API_KEY)


def get_login_url():
    kite = create_kite_client()
    return kite.login_url()


def generate_session(request_token: str):
    kite = create_kite_client()

    return kite.generate_session(
        request_token,
        api_secret=KITE_API_SECRET
    )


if __name__ == "__main__":

    print("\n========================================")
    print("       NIFTY OPTIONS BLAST ENGINE")
    print("          Kite Authentication")
    print("========================================\n")

    print("1. Open this URL in your browser:\n")
    print(get_login_url())

    print("\n2. Login to Zerodha.")
    print("3. Complete authentication.")
    print("4. Copy the NEW request_token from the redirect URL.\n")

    request_token = input("Enter NEW request token: ").strip()

    if not request_token:
        print("Request token cannot be empty.")
        exit(1)

    try:
        session_data = generate_session(request_token)
        update_access_token(session_data["access_token"])

        print("\n========================================")
        print("       Authentication Successful")
        print("========================================")
        print("User ID:", session_data["user_id"])
        print("Access token received:", bool(session_data["access_token"]))

    except Exception as e:
        print("\nAuthentication failed:")
        print(type(e).__name__, "-", e)
