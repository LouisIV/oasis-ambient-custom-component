"""Read-only account diagnostics. Never print credentials or account identifiers."""
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from urllib.error import HTTPError

root = Path(__file__).parent / 'private'
tokens = json.loads((root / 'oauth-account-tokens.json').read_text())
session = json.loads((root / 'oauth-account-session.json').read_text())
try:
    request = Request(session['auth_origin'] + '/oauth2/token', data=urlencode({
        'grant_type': 'refresh_token', 'client_id': session['client_id'],
        'refresh_token': tokens['refresh_token'],
    }).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urlopen(request, timeout=20) as response:
        access = json.load(response)['access_token']
    request = Request('https://0sb7eb48mj.execute-api.us-east-1.amazonaws.com/dev/v1/user/nodes?node_details=true',
                      headers={'Authorization': access})
    with urlopen(request, timeout=20) as response:
        data = json.load(response)
    summaries = []
    for node in data.get('node_details', []):
        config = node.get('config', {})
        info = config.get('info', {})
        allowed = {'Power', 'Brightness', 'CCT', 'Color', 'Light Mode', 'BLE Connected',
                   'Reset Reason', 'Boot Count', 'FW Version', 'meshRxCount', 'meshUnicast',
                   'meshIvIndex', 'meshSource', 'Largest Heap', 'Total Free Memory', 'Malloc Failures'}
        params = {device: {k: v for k, v in values.items() if k in allowed}
                  for device, values in node.get('params', {}).items() if isinstance(values, dict)}
        summaries.append({'firmware': info.get('fw_version'), 'model': info.get('model'),
            'diagnostics': params,
            'ble_parameter_schema': [p for d in config.get('devices', []) for p in d.get('params', [])
                                     if p.get('name') in {'BLE Connected', 'BLE Mesh Reset', 'meshRxCount'}],
            'status': node.get('status'),
            'devices': [{'type': d.get('type'), 'parameters': [p.get('name') for p in d.get('params', [])]}
                        for d in config.get('devices', [])],
            'services': [{'type': s.get('type'), 'parameters': [p.get('name') for p in s.get('params', [])]}
                         for s in config.get('services', [])]})
    print(json.dumps({'response_fields': list(data), 'nodes': summaries}))
except HTTPError as error:
    print(json.dumps({'http_status': error.code}))
