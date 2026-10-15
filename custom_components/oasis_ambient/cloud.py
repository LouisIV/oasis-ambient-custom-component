"""One-shot Oasis account import. Passwords and tokens are never persisted."""
import json
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from urllib.parse import urlencode

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


def _login(email, password):
    """Return a short-lived account token for one explicit cloud action."""
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
    return token


def fetch_account_meshes(email, password):
    """Run in the executor; return mesh data only, never account credentials."""
    token = _login(email, password)
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


def restart_account_lamp(email, password, lamp_name, unicast_address):
    """Restart one lamp through Oasis after explicit user confirmation.

    The access token remains local to this executor call and is never returned
    to the config flow or written to Home Assistant storage.
    """
    token = _login(email, password)
    nodes = _read(Request(API + '/user/nodes?node_details=true',
                          headers={'Authorization': token, 'Accept': 'application/json'}))
    expected_address = int(unicast_address, 16)
    matches = []
    for node in nodes.get('node_details', []):
        params = node.get('params') or {}
        values = [value for value in params.values() if isinstance(value, dict)]
        mesh_address = next((value.get('meshUnicast') for value in values
                             if value.get('meshUnicast') is not None), None)
        if mesh_address is None:
            continue
        try:
            if isinstance(mesh_address, str):
                try:
                    actual_address = int(mesh_address, 0)
                except ValueError:
                    actual_address = int(mesh_address, 16)
            else:
                actual_address = int(mesh_address)
            if actual_address == expected_address:
                matches.append(node)
        except (TypeError, ValueError):
            continue
    if len(matches) != 1:
        raise AccountError('lamp_not_found')
    node = matches[0]
    services = [service for service in node.get('config', {}).get('services', [])
                if service.get('type') == 'esp.service.system']
    reboot = [param for service in services for param in service.get('params', [])
              if param.get('name') == 'Reboot'
              and param.get('data_type') == 'bool'
              and 'write' in param.get('properties', [])]
    node_id = node.get('node_id')
    if len(services) != 1 or len(reboot) != 1 or not isinstance(node_id, str) or not node_id:
        raise AccountError('restart_unsupported')
    payload = {services[0]['name']: {'Reboot': True}}
    _read(Request(API + '/user/nodes/params?' + urlencode({'node_id': node_id}),
                  data=json.dumps(payload).encode(), method='PUT',
                  headers={'Authorization': token, 'Content-Type': 'application/json',
                           'Accept': 'application/json'}))
    return lamp_name
