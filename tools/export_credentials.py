"""Guided Oasis mesh exporter using official browser sign-in. Run on a desktop.

Only the final mesh export is written. OAuth state, codes, tokens, and browser
cookies are ephemeral. Never enable browser tracing/HAR for this login.
"""
import argparse
import asyncio
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

AUTH = 'https://mixtiles.auth.us-east-1.amazoncognito.com'
CLIENT_ID = '20hc2tbnm5cqipo83tq7fr6lt1'
CALLBACK = 'rainmaker://com.mixtiles.oasis/success'
GROUPS = 'https://0sb7eb48mj.execute-api.us-east-1.amazonaws.com/dev/v1/user/node_group'


class ExportError(Exception):
    """Safe, user-facing error; never attach an HTTP response or credential."""


class LoginSession:
    def __init__(self):
        self.verifier = secrets.token_urlsafe(48)
        self.state = secrets.token_urlsafe(32)
        self.started = time.monotonic()

    @property
    def url(self):
        challenge = base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).rstrip(b'=').decode()
        return AUTH + '/oauth2/authorize?' + urlencode({
            'client_id': CLIENT_ID, 'response_type': 'code', 'redirect_uri': CALLBACK,
            'scope': 'openid email aws.cognito.signin.user.admin', 'state': self.state,
            'code_challenge_method': 'S256', 'code_challenge': challenge})

    def code_from_callback(self, url):
        target, expected = urlsplit(url), urlsplit(CALLBACK)
        if (target.scheme, target.netloc, target.path) != (expected.scheme, expected.netloc, expected.path):
            raise ExportError('Unexpected login callback. Close the window and start again.')
        query = parse_qs(target.query, keep_blank_values=True)
        if time.monotonic() - self.started > 600 or query.get('state') != [self.state]:
            raise ExportError('Login expired or could not be verified. Please start again.')
        if 'error' in query:
            raise ExportError('Oasis did not authorize the login. Please try again.')
        if len(query.get('code', [])) != 1 or not query['code'][0]:
            raise ExportError('Oasis did not return a login code. Please try again.')
        return query['code'][0]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def read_json(request):
    try:
        with build_opener(NoRedirect()).open(request, timeout=30) as response:
            raw = response.read(5 * 1024 * 1024 + 1)
        if len(raw) > 5 * 1024 * 1024:
            raise ExportError('Oasis returned an unexpectedly large response.')
        return json.loads(raw)
    except HTTPError as error:
        raise ExportError(f'Oasis returned HTTP {error.code}. Try signing in again.') from None
    except (URLError, TimeoutError, ValueError):
        raise ExportError('Could not read the Oasis response. Check your connection and retry.') from None


def extract_meshes(groups):
    """Export meshes only, never the account profile, tokens, or automations."""
    meshes = {}
    for group in groups.get('groups', []):
        raw = (group.get('custom_data') or {}).get('ble_mesh_config', {}).get('mesh_data')
        if not raw:
            continue
        mesh = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(mesh, dict) or not mesh.get('meshUUID') or not mesh.get('netKeys'):
            raise ExportError('The account contains an unsupported mesh export.')
        previous = meshes.get(mesh['meshUUID'])
        if previous is not None and previous != mesh:
            raise ExportError('Oasis returned conflicting copies of a mesh. Refresh your lamps in the Oasis app, then retry.')
        meshes[mesh['meshUUID']] = mesh
    if not meshes:
        raise ExportError('No mesh lamps found. Pair a lamp in the Oasis app first, then export again.')
    return {'oasis_export': 1, 'meshes': list(meshes.values())}


def exchange_and_export(session, code):
    body = urlencode({'grant_type': 'authorization_code', 'client_id': CLIENT_ID,
                      'redirect_uri': CALLBACK, 'code_verifier': session.verifier, 'code': code}).encode()
    tokens = read_json(Request(AUTH + '/oauth2/token', data=body,
                              headers={'Content-Type': 'application/x-www-form-urlencoded'}))
    if not tokens.get('access_token'):
        raise ExportError('Oasis did not return an account access token. Please retry.')
    groups = read_json(Request(GROUPS, headers={'Authorization': tokens['access_token'],
                                               'Accept': 'application/json'}))
    return extract_meshes(groups)


def write_export(target, payload):
    with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as output:
        json.dump(payload, output)


async def browser_login(session):
    try:
        from playwright.async_api import async_playwright, Error as BrowserError
    except ImportError:
        raise ExportError('Install the exporter dependencies first: python -m pip install -r tools/requirements.txt') from None
    async with async_playwright() as playwright:
        try:
            browser = await playwright.chromium.launch(headless=False)
        except BrowserError:
            raise ExportError('Install the login browser first: python -m playwright install chromium') from None
        try:
            context = await browser.new_context()
            result = asyncio.get_running_loop().create_future()

            async def receive(response):
                # Only Oasis Cognito may supply the custom-scheme redirect.
                if urlsplit(response.url).netloc != urlsplit(AUTH).netloc:
                    return
                try:
                    location = (await response.all_headers()).get('location', '')
                    if not location.startswith('rainmaker:') or result.done():
                        return
                    result.set_result(session.code_from_callback(location))
                except ExportError as error:
                    if not result.done():
                        result.set_exception(error)
                except BrowserError:
                    pass

            context.on('response', receive)
            context.on('close', lambda: result.set_exception(ExportError('Login window closed. Run the exporter again.')) if not result.done() else None)
            page = await context.new_page()
            print('Sign in on the official Oasis page in the browser. Your password stays on that page.', flush=True)
            try:
                await page.goto(session.url, wait_until='domcontentloaded')
            except BrowserError:
                if not result.done():
                    raise ExportError('The login page could not open. Check your connection and retry.') from None
            try:
                return await asyncio.wait_for(result, 600)
            except TimeoutError:
                raise ExportError('Login timed out after 10 minutes. Run the exporter again.') from None
        finally:
            await browser.close()


async def run(target):
    if target.exists():
        raise ExportError('That export file already exists. Choose a different --output path to keep the old file safe.')
    session = LoginSession()
    code = await browser_login(session)
    print('Signed in. Retrieving your lamp networks…', flush=True)
    payload = await asyncio.to_thread(exchange_and_export, session, code)
    write_export(target, payload)
    print(f'Saved {len(payload["meshes"])} mesh network(s) to {target}.')
    print('In Home Assistant: Add Oasis Ambient → Import credentials → choose this file → select your lamps.')
    print('Keep this file private: it grants control of your lamps. No account tokens were saved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('oasis-credentials.json'))
    args = parser.parse_args()
    try:
        asyncio.run(run(args.output))
    except (ExportError, OSError) as error:
        print(f'Export not completed: {error}', file=sys.stderr)
        return 1
    except (ValueError, KeyError, TypeError):
        print('Export not completed: Oasis returned an unsupported response. No credentials were printed.', file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print('\nExport cancelled.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
