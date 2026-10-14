"""Local mesh proxy transport. Successful send is NOT lamp state readback.

The caller owns device discovery and sequence storage location. Never restore
an old sequence database or share one sender address across independent hosts.
"""
import asyncio
import hashlib
import logging
from contextlib import asynccontextmanager
from bleak.exc import BleakError
from pathlib import Path

from .mesh_crypto import NetworkMessage, authenticate_beacon, encrypt_access, encrypt_network
from .mesh_protocol import ProxyReassembler, SecureNetworkBeacon, fragment_proxy
from .sequence_store import SequenceStore

PROXY_IN = '00002add-0000-1000-8000-00805f9b34fb'
PROXY_OUT = '00002ade-0000-1000-8000-00805f9b34fb'
_LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def connected_client(device, timeout=20):
    """Retry connection establishment only; never replay an access-message batch."""
    from bleak_retry_connector import establish_connection, BleakClientWithServiceCache

    client = await establish_connection(
        BleakClientWithServiceCache, device, device.name or device.address,
        max_attempts=3, timeout=timeout, use_services_cache=False,
    )
    try:
        missing = [uuid for uuid in (PROXY_IN, PROXY_OUT)
                   if client.services.get_characteristic(uuid) is None]
        if missing:
            # Preserve discovery evidence. On Linux cache clearing may remove
            # the BlueZ device; do not do that automatically or reconnect using
            # the same potentially invalid BLEDevice.
            inventory = [(service.uuid,
                          [char.uuid for char in service.characteristics])
                         for service in client.services]
            _LOGGER.warning('Incomplete proxy GATT discovery for %s. '
                            'Services/characteristics: %s; disconnecting without cache removal',
                            device.address, inventory)
            raise BleakError('Mesh proxy characteristics missing after discovery: '
                             + ', '.join(missing))
        yield client
    finally:
        await client.disconnect()


class OasisController:
    def __init__(self, mesh, lamp_name, source, sequence_path, *, client_factory=connected_client,
                 destination=None, lock=None):
        nodes = [n for n in mesh['nodes'] if (int(n['unicastAddress'], 16) == destination
                 if destination is not None else n.get('name') == lamp_name)]
        if len(nodes) != 1:
            raise ValueError('Exactly one matching lamp is required')
        lamp = nodes[0]
        self.destination = int(lamp['unicastAddress'], 16)
        if not 1 <= source <= 0x7fff:
            raise ValueError('Invalid sender address')
        for node in mesh['nodes']:
            first = int(node['unicastAddress'], 16)
            if first <= source < first + max(1, len(node.get('elements', []))):
                raise ValueError('Sender conflicts with an existing mesh node')
        for provisioner in mesh.get('provisioners', []):
            for allocation in provisioner.get('allocatedUnicastRange', []):
                if int(allocation['lowAddress'], 16) <= source <= int(allocation['highAddress'], 16):
                    raise ValueError('Sender conflicts with a provisioner allocation')
        models = lamp['elements'][0]['models']
        vendor = next(m for m in models if m['modelId'].upper() == '02E5C00A')
        if 0 not in vendor.get('bind', []):
            raise ValueError('Expected vendor model is not bound to AppKey0')
        self.net_key = bytes.fromhex(next(k['key'] for k in mesh['netKeys'] if k['index'] == 0))
        app = next(k for k in mesh['appKeys'] if k['index'] == 0)
        if app['boundNetKey'] != 0:
            raise ValueError('AppKey0 must be bound to NetKey0')
        self.app_key = bytes.fromhex(app['key'])
        if len(self.net_key) != 16 or len(self.app_key) != 16:
            raise ValueError('Invalid mesh key length')
        self.identity = mesh['meshUUID'] + ':' + hashlib.sha256(self.net_key).hexdigest()
        self.source = source
        self.sequence_path = Path(sequence_path)
        self.client_factory = client_factory
        self.lock = lock if lock is not None else asyncio.Lock()

    def _allocate(self, iv_index, initialize):
        store = SequenceStore(self.sequence_path, self.identity, self.source, iv_index,
                              initialize=initialize)
        try:
            return store.allocate()
        finally:
            store.close()

    async def send(self, device, messages, *, initialize_sender=False, authenticate_only=False):
        """Send an ordered batch. No automatic resend of partially sent commands.

        initialize_sender is only appropriate for a newly reserved sender.
        Production callers must not silently recreate missing sequence state.
        """
        messages = tuple(messages)
        if (not messages and not (initialize_sender or authenticate_only)) or any(not isinstance(m, bytes) or not 1 <= len(m) <= 11 for m in messages):
            raise ValueError('Expected nonempty unsegmented access messages')
        async with self.lock:
            ready = asyncio.Event()
            state = {'iv': None, 'error': None}
            assembler = ProxyReassembler()

            def notify(_, value):
                try:
                    result = assembler.feed(value)
                    if result is None or result[0] != 1:
                        return
                    if not authenticate_beacon(self.net_key, result[1]):
                        return
                    beacon = SecureNetworkBeacon.parse(result[1])
                    if beacon.key_refresh or beacon.iv_update:
                        state['error'] = 'Unsupported mesh key/IV transition'
                    elif state['iv'] is not None and state['iv'] != beacon.iv_index:
                        state['error'] = 'IV changed during connection'
                    else:
                        state['iv'] = beacon.iv_index
                    ready.set()
                except ValueError:
                    return

            async with self.client_factory(device, timeout=20) as client:
                await client.start_notify(PROXY_OUT, notify)
                try:
                    await asyncio.wait_for(ready.wait(), 15)
                    if state['error']:
                        raise ValueError(state['error'])
                    if not messages:
                        # Setup authenticates the beacon and reserves a counter without
                        # changing the lamp. Only explicit setup may initialize state.
                        await asyncio.to_thread(self._allocate, state['iv'], initialize_sender)
                        return []
                    sequences = []
                    for access in messages:
                        if state['error']:
                            raise ValueError(state['error'])
                        iv = state['iv']
                        seq = await asyncio.to_thread(self._allocate, iv, initialize_sender)
                        if state['error']:
                            raise ValueError(state['error'])
                        lower = encrypt_access(self.app_key, iv, seq, self.source,
                                               self.destination, access)
                        pdu = encrypt_network(self.net_key, iv, NetworkMessage(
                            0, 5, seq, self.source, self.destination, lower))
                        for chunk in fragment_proxy(0, pdu):
                            await client.write_gatt_char(PROXY_IN, chunk, response=False)
                        sequences.append(seq)
                        if access[:3] == bytes.fromhex('cce502'):
                            # Preserve the mode-to-color spacing used in the real
                            # lamp verification; no automatic command retries.
                            await asyncio.sleep(0.3)
                    return sequences
                finally:
                    await client.stop_notify(PROXY_OUT)
