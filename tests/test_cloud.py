"""Account import never returns or persists account login secrets."""
import json
import importlib
import sys
import unittest
from urllib.error import HTTPError, URLError
from unittest.mock import MagicMock, patch

from test_config_flow import PACKAGE
from test_onboarding import fixture_mesh

with patch.dict(sys.modules, {'oasis_flow_test': PACKAGE}):
    CLOUD = importlib.import_module('oasis_flow_test.cloud')


class AccountTests(unittest.TestCase):
    def test_login_then_mesh_fetch_returns_only_meshes(self):
        mesh = fixture_mesh()
        groups = {'groups': [{'custom_data': {'ble_mesh_config': {'mesh_data': json.dumps(mesh)}}}],
                  'private_profile': 'not-returned'}
        with patch.object(CLOUD, '_read', side_effect=[
                {'status': 'success', 'accesstoken': 'secret-token', 'refreshtoken': 'secret-refresh'}, groups]) as read:
            result = CLOUD.fetch_account_meshes(' user@example.com ', ' password ')
        login, fetch = [call.args[0] for call in read.call_args_list]
        self.assertEqual(json.loads(login.data), {'user_name': 'user@example.com', 'password': ' password '})
        self.assertEqual(login.full_url, CLOUD.API + '/login2')
        self.assertEqual(fetch.full_url, CLOUD.API + '/user/node_group')
        self.assertEqual(fetch.get_header('Authorization'), 'secret-token')
        self.assertEqual(result, [mesh])
        self.assertNotIn('secret', json.dumps(result))

    def test_challenge_does_not_fetch_meshes(self):
        with patch.object(CLOUD, '_read', return_value={'status': 'success', 'session': 'secret-session'}) as read:
            with self.assertRaisesRegex(CLOUD.AccountError, '^additional_auth_required$'):
                CLOUD.fetch_account_meshes('email', 'password')
        self.assertEqual(read.call_count, 1)

    def test_malformed_and_conflicting_meshes_rejected(self):
        a, b = fixture_mesh(), fixture_mesh()
        b['nodes'][0]['unicastAddress'] = '0009'
        cases = [({}, 'invalid_account_data'), ({'groups': []}, 'no_lamps'),
                 ({'groups': [None]}, 'invalid_account_data'),
                 ({'groups': [{'custom_data': {'ble_mesh_config': {'mesh_data': mesh}}}
                              for mesh in (a, b)]}, 'invalid_account_data')]
        for groups, code in cases:
            with self.subTest(groups=groups), patch.object(CLOUD, '_read', side_effect=[
                    {'status': 'success', 'accesstoken': 'token'}, groups]):
                with self.assertRaisesRegex(CLOUD.AccountError, '^' + code + '$'):
                    CLOUD.fetch_account_meshes('email', 'password')

    def test_transport_errors_are_sanitized_and_not_retried(self):
        cases = [(HTTPError('secret-url', 401, 'secret', {}, None), 'invalid_auth'),
                 (HTTPError('secret-url', 429, 'secret', {}, None), 'rate_limited'),
                 (HTTPError('secret-url', 302, 'secret', {}, None), 'account_unavailable'),
                 (URLError('secret'), 'account_unavailable')]
        for error, code in cases:
            opener = MagicMock()
            opener.open.side_effect = error
            with self.subTest(code=code), patch.object(CLOUD, 'build_opener', return_value=opener):
                with self.assertRaisesRegex(CLOUD.AccountError, '^' + code + '$'):
                    CLOUD._read(object())
            self.assertEqual(opener.open.call_count, 1)

    def test_response_size_and_shape_limits(self):
        for raw in (b'not-json', b'[]', b'x' * (CLOUD.MAX_EXPORT_BYTES + 1)):
            opener = MagicMock()
            opener.open.return_value.__enter__.return_value.read.return_value = raw
            with patch.object(CLOUD, 'build_opener', return_value=opener):
                with self.assertRaisesRegex(CLOUD.AccountError, '^invalid_account_data$'):
                    CLOUD._read(object())
