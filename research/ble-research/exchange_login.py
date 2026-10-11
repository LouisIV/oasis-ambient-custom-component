"""Consume an Oasis OAuth callback URL on stdin and save tokens privately."""
import json
import argparse
import os
from pathlib import Path
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError

root = Path(__file__).resolve().parent / "private"
parser = argparse.ArgumentParser()
parser.add_argument("--account-api", action="store_true")
args = parser.parse_args()
session = json.loads((root / ("oauth-account-session.json" if args.account_api else "oauth-session.json")).read_text())
callback = urlsplit(sys.stdin.read().strip())
expected = urlsplit(session["redirect_uri"])
if (callback.scheme, callback.netloc, callback.path) != (expected.scheme, expected.netloc, expected.path):
    raise SystemExit("Unexpected callback origin/path")
query = parse_qs(callback.query)
if query.get("state") != [session["state"]] or len(query.get("code", [])) != 1:
    raise SystemExit("Invalid state or missing authorization code")
body = urlencode({"grant_type": "authorization_code", "client_id": session["client_id"],
                  "redirect_uri": session["redirect_uri"], "code_verifier": session["verifier"],
                  "code": query["code"][0]}).encode()
request = Request(session["auth_origin"] + "/oauth2/token", data=body,
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
try:
    with urlopen(request, timeout=20) as response:
        tokens = json.load(response)
except HTTPError as error:
    # Only report OAuth error type, never request/response tokens.
    try:
        detail = json.load(error).get("error", "unknown")
    except Exception:
        detail = "unreadable error"
    raise SystemExit(f"Token exchange failed: HTTP {error.code}, {detail}")
if not tokens.get("id_token") or not tokens.get("access_token"):
    raise SystemExit("Token response incomplete")
tokens["received_at"] = time.time()
target = root / ("oauth-account-tokens.json" if args.account_api else "oauth-tokens.json")
with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
    json.dump(tokens, output)
print(json.dumps({"tokens_saved": True, "expires_in": tokens.get("expires_in"),
                  "refresh_available": bool(tokens.get("refresh_token"))}))
