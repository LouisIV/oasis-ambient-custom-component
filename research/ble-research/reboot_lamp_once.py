"""One explicitly approved software reboot. No automatic retries or resets."""
import json
import argparse
import runpy
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

parser = argparse.ArgumentParser()
parser.add_argument('--confirm-software-reboot', action='store_true', required=True,
                    help='Requires explicit owner approval; sends one reboot without retry')
parser.parse_args()

state = runpy.run_path(str(Path(__file__).with_name('check_account_metadata.py')))
nodes = state['data'].get('node_details', [])
assert len(nodes) == 1, 'Refuse ambiguous target'
node = nodes[0]
assert node['config']['info']['model'] == 'ambient_2_0'
assert node['params']['Light']['meshUnicast'] == 2
services = [s for s in node['config']['services'] if s.get('type') == 'esp.service.system']
assert len(services) == 1
service = services[0]
reboot = next(p for p in service['params'] if p['name'] == 'Reboot')
assert reboot['data_type'] == 'bool' and 'write' in reboot['properties']
payload = {service['name']: {'Reboot': True}}
url = 'https://0sb7eb48mj.execute-api.us-east-1.amazonaws.com/dev/v1/user/nodes/params?'
request = Request(url + urlencode({'node_id': node['node_id']}),
                  data=json.dumps(payload).encode(), method='PUT',
                  headers={'Authorization': state['access'], 'Content-Type': 'application/json'})
with urlopen(request, timeout=20) as response:
    result = json.load(response)
    print(json.dumps({'reboot_request_http_status': response.status,
                      'status': result.get('status'), 'description': result.get('description')}))
