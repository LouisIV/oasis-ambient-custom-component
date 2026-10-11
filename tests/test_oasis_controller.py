import tempfile
import unittest
from pathlib import Path

from mesh_crypto import beacon_key, cmac, k3, decrypt_network, decrypt_access
from mesh_protocol import fragment_proxy, ProxyReassembler
from oasis_commands import power
from oasis_controller import OasisController

KEY = bytes(range(16))
MESH = {'meshUUID': 'test-only', 'netKeys': [{'index': 0, 'key': KEY.hex()}],
        'appKeys': [{'index': 0, 'boundNetKey': 0, 'key': KEY.hex()}],
        'nodes': [{'name': 'test', 'unicastAddress': '0002', 'elements': [
            {'models': [{'modelId': '02E5C00A', 'bind': [0]}]}]}], 'provisioners': []}


class FakeClient:
    sent = []

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
            self.sent.append((msg.sequence, decrypt_access(KEY, 0, msg)))


class ControllerTest(unittest.IsolatedAsyncioTestCase):
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
