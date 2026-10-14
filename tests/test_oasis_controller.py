import tempfile
import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from pathlib import Path

from mesh_crypto import beacon_key, cmac, k3, decrypt_network, decrypt_access
from mesh_protocol import fragment_proxy, ProxyReassembler
from oasis_commands import power
from oasis_controller import OasisController, connected_client

KEY = bytes(range(16))
MESH = {'meshUUID': 'test-only', 'netKeys': [{'index': 0, 'key': KEY.hex()}],
        'appKeys': [{'index': 0, 'boundNetKey': 0, 'key': KEY.hex()}],
        'nodes': [{'name': 'test', 'unicastAddress': '0002', 'elements': [
            {'models': [{'modelId': '02E5C00A', 'bind': [0]}]}]}], 'provisioners': []}


class FakeClient:
    sent = []
    destinations = []

    def __init__(self, device, timeout):
        self.assembler = ProxyReassembler()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def start_notify(self, char, callback):
        data = bytes([0]) + k3(KEY) + bytes(4)
        beacon = bytes([1]) + data + cmac(beacon_key(KEY), data)[:8]
        for chunk in fragment_proxy(1, beacon):
            callback(None, chunk)

    async def stop_notify(self, char):
        pass

    async def write_gatt_char(self, char, chunk, response):
        result = self.assembler.feed(chunk)
        if result:
            msg = decrypt_network(KEY, 0, result[1])
            self.destinations.append(msg.destination)
            self.sent.append((msg.sequence, decrypt_access(KEY, 0, msg)))


class ControllerTest(unittest.IsolatedAsyncioTestCase):
    async def test_connector_disconnects_without_replaying_failed_batch(self):
        client = SimpleNamespace(disconnect=AsyncMock(), services=Mock())
        establish = AsyncMock(return_value=client)
        backend = SimpleNamespace(establish_connection=establish,
                                  BleakClientWithServiceCache=object)
        device = SimpleNamespace(name='test', address='test-address')
        with patch.dict('sys.modules', {'bleak_retry_connector': backend}):
            with self.assertRaisesRegex(ValueError, 'send failed'):
                async with connected_client(device) as connected:
                    self.assertIs(connected, client)
                    raise ValueError('send failed')
        establish.assert_awaited_once_with(object, device, 'test', max_attempts=3, timeout=20,
                                          use_services_cache=False)
        client.disconnect.assert_awaited_once()

    async def test_connector_disconnects_after_success(self):
        client = SimpleNamespace(disconnect=AsyncMock(), services=Mock())
        backend = SimpleNamespace(establish_connection=AsyncMock(return_value=client),
                                  BleakClientWithServiceCache=object)
        with patch.dict('sys.modules', {'bleak_retry_connector': backend}):
            async with connected_client(SimpleNamespace(name=None, address='test-address')):
                pass
        client.disconnect.assert_awaited_once()

    async def test_missing_proxy_services_refresh_before_any_send(self):
        stale = SimpleNamespace(disconnect=AsyncMock(), clear_cache=AsyncMock(),
                                services=Mock(get_characteristic=Mock(return_value=None)))
        fresh = SimpleNamespace(disconnect=AsyncMock(), services=Mock())
        establish = AsyncMock(side_effect=[stale, fresh])
        backend = SimpleNamespace(establish_connection=establish, BleakClientWithServiceCache=object)
        with patch.dict('sys.modules', {'bleak_retry_connector': backend}):
            async with connected_client(SimpleNamespace(name='test', address='test')) as client:
                self.assertIs(client, fresh)
        stale.clear_cache.assert_awaited_once()
        stale.disconnect.assert_awaited_once()
        fresh.disconnect.assert_awaited_once()
        self.assertEqual(establish.await_count, 2)

    async def test_missing_services_recovery_is_bounded(self):
        from bleak.exc import BleakError
        client = SimpleNamespace(disconnect=AsyncMock(), clear_cache=AsyncMock(),
                                 services=Mock(get_characteristic=Mock(return_value=None)))
        establish = AsyncMock(return_value=client)
        backend = SimpleNamespace(establish_connection=establish, BleakClientWithServiceCache=object)
        with patch.dict('sys.modules', {'bleak_retry_connector': backend}):
            with self.assertRaisesRegex(BleakError, 'missing after fresh discovery'):
                async with connected_client(SimpleNamespace(name='test', address='test')):
                    self.fail('Must not send through a non-proxy connection')
        self.assertEqual(establish.await_count, 2)
        self.assertEqual(client.disconnect.await_count, 2)
        client.clear_cache.assert_awaited_once()

    async def test_two_destinations_use_shared_monotonic_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            mesh = copy.deepcopy(MESH)
            second = copy.deepcopy(mesh['nodes'][0])
            second['unicastAddress'] = '0003'
            mesh['nodes'].append(second)
            path = Path(directory) / 'seq.db'
            lock = asyncio.Lock()
            a = OasisController(mesh, 'test', 0x7ffe, path, destination=2,
                                lock=lock, client_factory=FakeClient)
            b = OasisController(mesh, 'test', 0x7ffe, path, destination=3,
                                lock=lock, client_factory=FakeClient)
            await a.send(None, [], initialize_sender=True)
            FakeClient.sent, FakeClient.destinations = [], []
            await asyncio.gather(a.send(None, [power(True)]), b.send(None, [power(False)]))
            self.assertEqual([seq for seq, _ in FakeClient.sent], [1, 2])
            self.assertEqual(FakeClient.destinations, [2, 3])
            self.assertIs(a.lock, b.lock)

    async def test_authenticate_only_does_not_recreate_lost_counter(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = OasisController(MESH, 'test', 0x7ffe, Path(directory) / 'missing.db',
                                         client_factory=FakeClient)
            with self.assertRaisesRegex(ValueError, 'state missing'):
                await controller.send(None, [], authenticate_only=True)

    async def test_setup_does_not_send_lighting_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            FakeClient.sent = []
            controller = OasisController(MESH, 'test', 0x7ffe, Path(directory) / 'seq.db',
                                         client_factory=FakeClient)
            self.assertEqual(await controller.send(None, [], initialize_sender=True), [])
            self.assertEqual(FakeClient.sent, [])
            await controller.send(None, [power(True)])
            self.assertEqual(FakeClient.sent, [(1, power(True))])

    async def test_encrypted_roundtrip_and_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'seq.db'
            FakeClient.sent = []
            controller = OasisController(MESH, 'test', 0x7fff, path, client_factory=FakeClient)
            await controller.send(None, [power(False)], initialize_sender=True)
            restarted = OasisController(MESH, 'test', 0x7fff, path, client_factory=FakeClient)
            await restarted.send(None, [power(True)])
            self.assertEqual(FakeClient.sent, [(0, power(False)), (1, power(True))])

    async def test_missing_counter_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = OasisController(MESH, 'test', 0x7fff, Path(directory) / 'seq.db',
                                         client_factory=FakeClient)
            with self.assertRaisesRegex(ValueError, 'state missing'):
                await controller.send(None, [power(False)])

    def test_address_conflict(self):
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            OasisController(MESH, 'test', 2, Path('unused'))
