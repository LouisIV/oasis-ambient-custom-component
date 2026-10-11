"""Pure import/export and sender-allocation tests; no real credentials."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


onboarding = load('onboarding', ROOT / 'custom_components/oasis_ambient/onboarding.py')
exporter = load('exporter', ROOT / 'tools/export_credentials.py')


def fixture_mesh(uuid='test-network'):
    return {'meshUUID': uuid, 'netKeys': [{'index': 0, 'key': '01' * 16}],
            'appKeys': [{'index': 0, 'boundNetKey': 0, 'key': '02' * 16}],
            'nodes': [{'name': f'OASIS_test{i}', 'unicastAddress': f'{i:04x}',
                       'elements': [{'models': [{'modelId': '02E5C00A', 'bind': [0]}]}]}
                      for i in (2, 3)],
            'provisioners': [{'allocatedUnicastRange': [{'lowAddress': '0001', 'highAddress': '0200'}]}]}


class OnboardingTests(unittest.TestCase):
    def test_multi_network_and_single_legacy_import(self):
        a, b = fixture_mesh(), fixture_mesh('another')
        self.assertEqual(len(onboarding.parse_export(json.dumps(a))), 1)
        meshes = onboarding.parse_export(json.dumps({'oasis_export': 1, 'meshes': [a, b]}))
        self.assertEqual(len(onboarding.lamp_choices(meshes)), 4)

    def test_reject_malformed_and_large_file(self):
        for raw in ('[]', '{}', '{', '{"oasis_export":1,"meshes":[1]}'):
            with self.assertRaises(ValueError):
                onboarding.parse_export(raw)
        with self.assertRaises(ValueError):
            onboarding.parse_export('x' * (onboarding.MAX_EXPORT_BYTES + 1))

    def test_reservations_unique_and_outside_existing_allocations(self):
        with tempfile.TemporaryDirectory() as directory:
            a, pa = onboarding.reserve_sender(fixture_mesh(), directory)
            b, pb = onboarding.reserve_sender(fixture_mesh(), directory)
            self.assertNotEqual(a, b)
            self.assertGreater(a, 0x200)
            self.assertNotEqual(a, 0x7fff)
            self.assertTrue(pa.is_dir() and pb.is_dir())

    def test_private_exclusive_export(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'export.json'
            exporter.write_export(target, {'oasis_export': 1, 'meshes': [fixture_mesh()]})
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(FileExistsError):
                exporter.write_export(target, {})

    def test_pkce_and_callback_validation(self):
        session = exporter.LoginSession()
        params = parse_qs(urlsplit(session.url).query)
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.assertIn('aws.cognito.signin.user.admin', params['scope'][0])
        good = exporter.CALLBACK + '?state=' + session.state + '&code=test'
        self.assertEqual(session.code_from_callback(good), 'test')
        for bad in (good.replace('rainmaker:', 'https:'), good.replace(session.state, 'wrong'), good + '&code=duplicate'):
            with self.assertRaises(exporter.ExportError):
                session.code_from_callback(bad)
        session.started -= 601
        with self.assertRaises(exporter.ExportError):
            session.code_from_callback(good)

    def test_extract_only_meshes_not_profile_or_tokens(self):
        groups = {'account_token': 'never-save', 'groups': [
            {'custom_data': {'ble_mesh_config': {'mesh_data': json.dumps(fixture_mesh())}}, 'automation': 'private'},
            {'custom_data': {'ble_mesh_config': {'mesh_data': fixture_mesh('second')}}}]}
        output = exporter.extract_meshes(groups)
        self.assertEqual(len(output['meshes']), 2)
        self.assertNotIn('never-save', json.dumps(output))
        self.assertNotIn('automation', json.dumps(output))

    def test_empty_account_actionable_error(self):
        with self.assertRaisesRegex(exporter.ExportError, 'Pair a lamp'):
            exporter.extract_meshes({'groups': []})

    def test_account_scope_exchange_and_raw_authorization(self):
        session = exporter.LoginSession()
        groups = {'groups': [{'custom_data': {'ble_mesh_config': {'mesh_data': fixture_mesh()}}}]}
        with patch.object(exporter, 'read_json', side_effect=[{'access_token': 'test-token'}, groups]) as read:
            output = exporter.exchange_and_export(session, 'test-code')
        self.assertEqual(len(output['meshes']), 1)
        request = read.call_args_list[1].args[0]
        self.assertEqual(request.get_header('Authorization'), 'test-token')
        self.assertEqual(request.full_url, exporter.GROUPS)
