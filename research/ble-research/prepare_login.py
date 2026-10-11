"""Prepare Oasis's public-client OAuth login with PKCE, without collecting a password."""
import base64
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parent / "private"
AUTH_ORIGIN = "https://mixtiles.auth.us-east-1.amazoncognito.com"
CLIENT_ID = "20hc2tbnm5cqipo83tq7fr6lt1"
REDIRECT_URI = "rainmaker://com.mixtiles.oasis/success"


def prepare():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account-api", action="store_true", help="Include RainMaker's required Cognito self-service scope")
    args = parser.parse_args()
    ROOT.mkdir(mode=0o700, exist_ok=True)
    target = ROOT / ("oauth-account-session.json" if args.account_api else "oauth-session.json")
    if target.exists():
        raise SystemExit("An OAuth session already exists; reuse it rather than invalidating an ongoing login.")
    verifier = secrets.token_urlsafe(48)
    state = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    params = {"client_id": CLIENT_ID, "response_type": "code", "redirect_uri": REDIRECT_URI,
              "scope": "openid email" + (" aws.cognito.signin.user.admin" if args.account_api else ""), "state": state,
              "code_challenge_method": "S256", "code_challenge": challenge}
    url = AUTH_ORIGIN + "/oauth2/authorize?" + urlencode(params)
    session = {"auth_origin": AUTH_ORIGIN, "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI,
               "state": state, "verifier": verifier, "login_url": url}
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
        json.dump(session, output)
    print(url)


if __name__ == "__main__":
    prepare()
