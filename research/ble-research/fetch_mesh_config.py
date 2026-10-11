"""Read the account's RainMaker groups; save private response, print only structure."""
import json
import argparse
import os
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

root = Path(__file__).resolve().parent / "private"
token_path = root / "oauth-account-tokens.json"
if not token_path.exists():
    token_path = root / "oauth-tokens.json"
tokens = json.loads(token_path.read_text())
parser = argparse.ArgumentParser()
parser.add_argument("--stage", choices=("dev", "prod", "api"), default="dev")
parser.add_argument("--token", choices=("id_token", "access_token"), default="access_token")
parser.add_argument("--bearer", action="store_true")
args = parser.parse_args()
# Host and API version/path are extracted from Oasis 2.4.0 Dart AOT strings.
url = f"https://0sb7eb48mj.execute-api.us-east-1.amazonaws.com/{args.stage}/v1/user/node_group"
authorization = ("Bearer " if args.bearer else "") + tokens[args.token]
request = Request(url, headers={"Authorization": authorization, "Accept": "application/json"})
try:
    with urlopen(request, timeout=20) as response:
        data = json.load(response)
except HTTPError as error:
    print(json.dumps({"status": error.code, "body": error.read(1000).decode(errors="replace")}))
    raise SystemExit(1)
target = root / "node-groups.json"
with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
    json.dump(data, output)

def shape(value, depth=0):
    if depth > 5:
        return type(value).__name__
    if isinstance(value, dict):
        return {key: shape(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return {"count": len(value), "sample_shape": shape(value[0], depth + 1) if value else None}
    return type(value).__name__

print(json.dumps({"saved": True, "response_shape": shape(data)}))
