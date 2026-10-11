"""Multi-lamp flow tests with HA API doubles and real durable sequence files."""
import asyncio
from contextlib import contextmanager
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, patch
from test_onboarding import fixture_mesh

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/oasis_ambient'


class FlowBase:
    def __init_subclass__(cls, **kwargs):
        pass
    def async_show_form(self, **kwargs):
        return dict(type='form', **kwargs)
    def async_show_menu(self, **kwargs):
        return dict(type='menu', **kwargs)
    def async_show_progress(self, **kwargs):
        return dict(type='progress', **kwargs)
    def async_show_progress_done(self, **kwargs):
        return dict(type='progress_done', **kwargs)
    def async_create_entry(self, **kwargs):
        return dict(type='create_entry', **kwargs)


def load_flow():
    names = ['homeassistant', 'homeassistant.config_entries', 'homeassistant.components',
             'homeassistant.components.bluetooth', 'homeassistant.components.file_upload',
             'homeassistant.core', 'homeassistant.helpers', 'homeassistant.helpers.selector',
             'homeassistant.exceptions']
    mods = {name: types.ModuleType(name) for name in names}
    mods['homeassistant.config_entries'].ConfigFlow = FlowBase
    mods['homeassistant.config_entries'].OptionsFlow = FlowBase
    mods['homeassistant.core'].callback = lambda fn: fn
    mods['homeassistant.exceptions'].ConfigEntryError = RuntimeError
    bluetooth = mods['homeassistant.components.bluetooth']
    bluetooth.async_discovered_service_info = lambda hass, **_: hass.nearby
    bluetooth.async_ble_device_from_address = lambda hass, address, **_: (
        object() if any(info.address == address for info in hass.nearby) else None)
    @contextmanager
    def upload(hass, path):
        yield Path(path)
    mods['homeassistant.components.file_upload'].process_uploaded_file = upload
    class Selector:
        def __init__(self, config):
            self.config = config
        def __call__(self, value):
            return value
    selectors = mods['homeassistant.helpers.selector']
    selectors.FileSelector = selectors.SelectSelector = Selector
    selectors.FileSelectorConfig = selectors.SelectSelectorConfig = dict
    with patch.dict(sys.modules, mods):
        spec = importlib.util.spec_from_file_location('oasis_flow_test', ROOT / '__init__.py',
                                                     submodule_search_locations=[str(ROOT)])
        package = importlib.util.module_from_spec(spec)
        sys.modules['oasis_flow_test'] = package
        spec.loader.exec_module(package)
        spec = importlib.util.spec_from_file_location('oasis_flow_test.config_flow', ROOT / 'config_flow.py')
        flow = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(flow)
    return package, flow


PACKAGE, FLOW = load_flow()


class FakeHass:
    def __init__(self, path):
        self.data = {}
        self.nearby = [types.SimpleNamespace(name=f'OASIS_test{i}', address=f'address-{i}') for i in (2, 3)]
        self.entries = []
        self.config = types.SimpleNamespace(path=lambda *parts: str(Path(path).joinpath(*parts)))
        self.config_entries = types.SimpleNamespace(async_entries=lambda _: self.entries,
            async_update_entry=lambda entry, **kwargs: setattr(entry, 'data', kwargs['data']),
            async_reload=AsyncMock())
    async def async_add_executor_job(self, function, *args):
        return function(*args)
    def async_create_task(self, coroutine):
        return asyncio.create_task(coroutine)


async def simulated_auth(controller, device, messages, *, initialize_sender=False, authenticate_only=False):
    if messages:
        raise AssertionError('Onboarding must never change a light')
    controller._allocate(0, initialize_sender)
    return []


class ConfigFlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.hass = FakeHass(self.directory.name)
        self.flow = FLOW.OasisConfigFlow()
        self.flow.hass = self.hass
        self.mesh = fixture_mesh()
        self.flow._meshes = {FLOW.mesh_identity(self.mesh): self.mesh}
        self.flow._loaded = True
        self.keys = list(FLOW.lamp_choices([self.mesh]))

    async def finish_selection(self, flow, keys):
        result = await flow.async_step_lamps({'lamps': keys})
        self.assertEqual(result['type'], 'progress')
        task = flow._connect_task
        with patch.object(FLOW.OasisController, 'send', simulated_auth):
            await task
        self.assertEqual((await flow.async_step_connect())['type'], 'progress_done')
        return await flow.async_step_finish()

    async def test_two_lamps_share_source_counter_but_not_destination(self):
        result = await self.finish_selection(self.flow, self.keys)
        lamps = result['data']['lamps']
        self.assertEqual(len(lamps), 2)
        self.assertEqual(lamps[0]['source'], lamps[1]['source'])
        self.assertEqual(lamps[0]['sequence_file'], lamps[1]['sequence_file'])
        self.assertNotEqual(lamps[0]['destination'], lamps[1]['destination'])
        self.assertNotEqual(lamps[0]['unique_id'], lamps[1]['unique_id'])

    async def test_add_lamps_preserves_existing_counter_and_identity(self):
        result = await self.finish_selection(self.flow, self.keys[:1])
        entry = types.SimpleNamespace(data=result['data'], unique_id=None, entry_id='existing')
        original = dict(entry.data['lamps'][0])
        self.hass.entries.append(entry)
        options = FLOW.OasisOptionsFlow(entry)
        options.hass = self.hass
        result = await self.finish_selection(options, self.keys[1:])
        self.assertEqual(result['type'], 'create_entry')
        self.assertEqual(entry.data['lamps'][0], original)
        self.assertEqual(entry.data['lamps'][1]['sequence_file'], original['sequence_file'])
        self.hass.config_entries.async_reload.assert_awaited_once_with('existing')

    async def test_offline_or_ambiguous_device_does_not_create_state(self):
        self.hass.nearby = []
        result = await self.flow.async_step_lamps({'lamps': self.keys})
        self.assertEqual(result['errors']['base'], 'not_nearby')
        self.assertIsNone(self.flow._connect_task)
        self.hass.nearby = [types.SimpleNamespace(name='OASIS_test2', address=x) for x in ('a', 'b')]
        self.assertIsNone(self.flow._nearby('OASIS_test2'))

    async def test_invalid_upload_is_recoverable(self):
        path = Path(self.directory.name) / 'bad.json'
        path.write_text('[]')
        result = await self.flow.async_step_upload({'credential_file': str(path)})
        self.assertEqual(result['step_id'], 'upload')
        self.assertEqual(result['errors']['base'], 'invalid_export')

    async def test_legacy_single_lamp_shape_preserved(self):
        entry = types.SimpleNamespace(data={'lamp_name': 'old', 'source': 10}, unique_id='old-id')
        self.assertEqual(PACKAGE.lamp_data(entry), [{'lamp_name': 'old', 'source': 10, 'unique_id': 'old-id'}])

    async def test_runtime_lock_shared_across_entries(self):
        self.assertIs(PACKAGE.network_lock(self.hass, 'same-mesh'), PACKAGE.network_lock(self.hass, 'same-mesh'))
        self.assertIsNot(PACKAGE.network_lock(self.hass, 'same-mesh'), PACKAGE.network_lock(self.hass, 'another-mesh'))

    async def test_missing_existing_counter_never_reinitialized(self):
        entry = types.SimpleNamespace(entry_id='old', unique_id=None, data={'lamps': [{
            'unique_id': self.keys[0], 'source': 32000, 'sequence_file': str(Path(self.directory.name) / 'missing.db'),
            'mesh_file': 'unused', 'lamp_name': 'OASIS_test2'}]})
        self.hass.entries.append(entry)
        with self.assertRaisesRegex(ValueError, 'counter missing'):
            await self.flow._connect_selected(self.keys[1:], FLOW.lamp_choices([self.mesh]))
