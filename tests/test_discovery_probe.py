"""Research captures must preserve evidence even without a GATT connection."""
import importlib.util
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch


PATH = Path(__file__).resolve().parents[1] / 'research/ble-research/probe.py'
SPEC = importlib.util.spec_from_file_location('discovery_probe', PATH)
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class DiscoveryProbeTests(unittest.IsolatedAsyncioTestCase):
    def test_identity_formats_and_malformed_payloads(self):
        for kind, length, name in [(0, 9, 'network_id'), (1, 17, 'node_identity'),
                                   (2, 17, 'private_network_identity'), (3, 17, 'private_node_identity')]:
            self.assertEqual(PROBE.proxy_identity(bytes([kind]) + bytes(length - 1)),
                             {'type': name, 'length_valid': True})
            self.assertFalse(PROBE.proxy_identity(bytes([kind]))['length_valid'])
        self.assertIsNone(PROBE.proxy_identity(None))
        self.assertEqual(PROBE.proxy_identity(b'\xff')['type'], 'unknown')

    async def test_scan_only_saves_unnamed_proxy_with_timestamps(self):
        class Scanner:
            def __init__(self, detection_callback):
                self.callback = detection_callback
            async def __aenter__(self):
                self.callback(types.SimpleNamespace(address='rotated', name=None),
                    types.SimpleNamespace(local_name=None, rssi=-40,
                        service_uuids=[PROBE.PROXY_UUID],
                        service_data={PROBE.PROXY_UUID: b'\x01' + bytes(16)}))
                return self
            async def __aexit__(self, *args):
                pass
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'capture.json'
            with patch('sys.argv', ['probe', '--all-proxies', '--seconds', '0', '--output', str(output)]), \
                 patch.object(PROBE, 'BleakScanner', Scanner), \
                 patch.object(PROBE, 'BleakClient') as client, patch('builtins.print'):
                await PROBE.main()
            records = json.loads(output.read_text())
            self.assertEqual(records[-1]['matches'], 1)
            self.assertEqual(records[1]['proxy_identity']['type'], 'node_identity')
            self.assertIn('timestamp', records[1])
            self.assertIn('elapsed_seconds', records[1])
            client.assert_not_called()

    async def test_broad_scan_cannot_connect(self):
        with patch('sys.argv', ['probe', '--all-proxies', '--inspect']), \
             patch.object(PROBE, 'BleakScanner') as scanner, patch('sys.stderr'):
            with self.assertRaises(SystemExit):
                await PROBE.main()
            scanner.assert_not_called()
