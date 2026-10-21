"""Adapter logic tests with explicit HA API doubles, not an HA runtime test."""
import importlib.util
import asyncio
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/oasis_ambient'


def load_light():
    package = types.ModuleType('oasis_adapter_test')
    package.__path__ = [str(ROOT)]
    package.network_proxy_for = lambda *_: types.SimpleNamespace(address="current-proxy")
    core = types.ModuleType('homeassistant.core')
    core.callback = lambda f: f
    event = types.ModuleType('homeassistant.helpers.event')
    event.async_track_time_interval = Mock()
    ha = types.ModuleType('homeassistant')
    components = types.ModuleType('homeassistant.components')
    bluetooth = types.ModuleType('homeassistant.components.bluetooth')
    components.bluetooth = bluetooth
    light = types.ModuleType('homeassistant.components.light')
    class Entity:
        def async_write_ha_state(self):
            self.written = True
        def async_schedule_update_ha_state(self):
            self.scheduled = True
    light.LightEntity = Entity
    light.ColorMode = types.SimpleNamespace(COLOR_TEMP='color_temp', RGB='rgb')
    light.ATTR_BRIGHTNESS = 'brightness'
    light.ATTR_COLOR_TEMP_KELVIN = 'color_temp_kelvin'
    light.ATTR_RGB_COLOR = 'rgb_color'
    exceptions = types.ModuleType('homeassistant.exceptions')
    exceptions.HomeAssistantError = RuntimeError
    modules = {'oasis_adapter_test': package, 'homeassistant': ha,
               'homeassistant.core': core,
               'homeassistant.helpers.event': event,
               'homeassistant.components': components,
               'homeassistant.components.bluetooth': bluetooth,
               'homeassistant.components.light': light,
               'homeassistant.exceptions': exceptions}
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location('oasis_adapter_test.light', ROOT / 'light.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        controller_module = importlib.import_module('oasis_adapter_test.protocol.oasis_controller')
    return module, controller_module.IncompleteProxyDiscovery


LIGHT, IncompleteProxyDiscovery = load_light()


class LightAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_advertisement_defers_availability_evaluation(self):
        self.entity._bluetooth_changed(object(), object())
        self.assertTrue(self.entity.scheduled)
        self.assertFalse(hasattr(self.entity, 'written'))

    async def test_periodic_reconciliation_recovers_without_advertisement_callback(self):
        removals = []
        self.entity.async_on_remove = removals.append
        cancel_timer = Mock()
        with patch.object(LIGHT, 'async_track_time_interval', return_value=cancel_timer) as timer, \
             patch.object(LIGHT.bluetooth, 'async_register_callback', create=True), \
             patch.object(LIGHT.bluetooth, 'async_track_unavailable', create=True), \
             patch.object(LIGHT.bluetooth, 'BluetoothScanningMode',
                          types.SimpleNamespace(ACTIVE='active', PASSIVE='passive'), create=True):
            await self.entity.async_added_to_hass()
        tick = timer.call_args.args[1]
        self.assertEqual(timer.call_args.args[2].total_seconds(), 30)
        for proxy in (None, types.SimpleNamespace(address='rotated-proxy'), None):
            with patch.object(LIGHT, 'network_proxy_for', return_value=proxy):
                self.entity.scheduled = False
                tick(None)
                self.assertTrue(self.entity.scheduled)
                self.assertEqual(self.entity.available, proxy is not None)
        self.controller.send.assert_not_awaited()
        self.assertIn(cancel_timer, removals)
        for remove in removals:
            remove()
        cancel_timer.assert_called_once()

    def setUp(self):
        self.controller = types.SimpleNamespace(send=AsyncMock(), net_key=bytes(16), identity='test-network')
        entry = types.SimpleNamespace(unique_id='test', data={'lamp_name': 'test', 'address': 'test'})
        self.entity = LIGHT.OasisLight(entry, self.controller)
        self.entity.hass = object()

    def messages(self):
        return self.controller.send.call_args.args[1]

    async def test_green_switches_mode_before_rgb(self):
        await self.entity.async_turn_on(rgb_color=(0, 255, 0))
        self.assertEqual([m.hex() for m in self.messages()], ['cce50201', 'c6e50200ff00', 'c3e50201'])
        self.assertEqual(self.entity._attr_color_mode, 'rgb')
        self.assertEqual(self.entity._attr_rgb_color, (0, 255, 0))

    async def test_cool_white_uses_combined_and_switches_mode(self):
        await self.entity.async_turn_on(brightness=255, color_temp_kelvin=6500)
        messages = self.messages()
        self.assertEqual(messages[0].hex(), 'cce50202')
        self.assertEqual(messages[1][:6].hex(), 'd2e502641964')
        self.assertEqual(len(messages[1]), 10)
        self.assertEqual(messages[2].hex(), 'c3e50201')
        self.assertEqual(self.entity._attr_color_mode, 'color_temp')

    async def test_zero_brightness_is_off(self):
        await self.entity.async_turn_on(brightness=0)
        self.assertEqual(self.messages(), [bytes.fromhex('c3e50200')])
        self.assertFalse(self.entity._attr_is_on)

    async def test_low_brightness_scales_to_percent(self):
        await self.entity.async_turn_on(brightness=1)
        self.assertEqual(self.messages()[0][:4].hex(), 'c4e50201')

    async def test_failed_send_does_not_claim_new_state(self):
        self.controller.send.side_effect = TimeoutError()
        with self.assertRaises(RuntimeError):
            await self.entity.async_turn_on(rgb_color=(0, 255, 0))
        self.assertIsNone(self.entity._attr_is_on)
        self.assertIsNone(self.entity._attr_rgb_color)

    async def test_incomplete_discovery_does_not_clear_cache_or_retry(self):
        error = IncompleteProxyDiscovery('Missing proxy output characteristic')
        self.controller.send.side_effect = error
        backend = types.SimpleNamespace(establish_connection=AsyncMock(),
                                        BleakClientWithServiceCache=object)
        with patch.dict(sys.modules, {'bleak_retry_connector': backend}):
            with self.assertRaisesRegex(RuntimeError, 'state not confirmed') as raised:
                await self.entity.async_turn_on(rgb_color=(0, 255, 0))
        self.assertIs(raised.exception.__cause__, error)
        self.controller.send.assert_awaited_once()
        backend.establish_connection.assert_not_awaited()
        self.assertIsNone(self.entity._attr_is_on)
        self.assertIsNone(self.entity._attr_rgb_color)
        self.assertFalse(hasattr(self.entity, 'written'))

    async def test_unreachable_proxy_does_not_send(self):
        with patch.object(LIGHT, 'network_proxy_for', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'not reachable'):
                await self.entity.async_turn_off()
        self.controller.send.assert_not_awaited()
        self.assertIsNone(self.entity._attr_is_on)

    async def test_cancelled_command_is_not_retried_or_reported_as_success(self):
        self.controller.send.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.entity.async_turn_off()
        self.controller.send.assert_awaited_once()
        self.assertIsNone(self.entity._attr_is_on)
        self.assertFalse(hasattr(self.entity, 'written'))

    async def test_conflicting_modes_rejected_before_transmit(self):
        with self.assertRaises(RuntimeError):
            await self.entity.async_turn_on(rgb_color=(0, 255, 0), color_temp_kelvin=6500)
        self.controller.send.assert_not_called()
