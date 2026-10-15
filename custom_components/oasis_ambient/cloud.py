"""One-shot Oasis account import. Passwords and tokens are never persisted."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .onboarding import MAX_EXPORT_BYTES, parse_export

API = 'https://0sb7eb48mj.execute-api.us-east-1.amazonaws.com/dev/v1'


class AccountError(Exception):
    """Only safe translation keys may reach the config flow."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _read(request):
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(MAX_EXPORT_BYTES + 1)
    except HTTPError as error:
        if error.code == 429:
            raise AccountError('rate_limited') from None
        if error.code in (400, 401, 403):
            raise AccountError('invalid_auth') from None
        raise AccountError('account_unavailable') from None
    except (URLError, TimeoutError, OSError):
        raise AccountError('account_unavailable') from None
    if len(raw) > MAX_EXPORT_BYTES:
        raise AccountError('invalid_account_data')
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise AccountError('invalid_account_data') from None
    if not isinstance(value, dict):
        raise AccountError('invalid_account_data')
    return value


def fetch_account_meshes(email, password):
    """Run in the executor; return mesh data only, never account credentials."""
    login = _read(Request(API + '/login2',
        data=json.dumps({'user_name': email.strip(), 'password': password}).encode(),
        headers={'Content-Type': 'application/json', 'Accept': 'application/json'}))
    if login.get('session') or login.get('ChallengeName'):
        raise AccountError('additional_auth_required')
    if login.get('status') != 'success':
        raise AccountError('invalid_auth')
    token = login.get('accesstoken')
    if not isinstance(token, str) or not token:
        raise AccountError('invalid_account_data')
    groups = _read(Request(API + '/user/node_group',
                          headers={'Authorization': token, 'Accept': 'application/json'}))
    try:
        if not isinstance(groups.get('groups'), list):
            raise ValueError('Missing group list')
        meshes = {}
        for group in groups['groups']:
            raw = (group.get('custom_data') or {}).get('ble_mesh_config', {}).get('mesh_data')
            if not raw:
                continue
            mesh = json.loads(raw) if isinstance(raw, str) else raw
            # Apply the same validation and limits as file import.
            mesh = parse_export(json.dumps(mesh))[0]
            identity = mesh['meshUUID']
            if identity in meshes and meshes[identity] != mesh:
                raise ValueError('Conflicting copies of a mesh')
            meshes[identity] = mesh
    except (ValueError, KeyError, TypeError, AttributeError):
        raise AccountError('invalid_account_data') from None
    if not meshes:
        raise AccountError('no_lamps')
    return list(meshes.values())
