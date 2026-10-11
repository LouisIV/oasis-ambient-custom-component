"""Adapter logic tests with explicit HA API doubles, not an HA runtime test."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1] / 'custom_components/oasis_ambient'


def load_light():
    package = types.ModuleType('oasis_adapter_test')
    package.__path__ = [str(ROOT)]
    package.device_for = lambda *_: object()
    ha = types.ModuleType('homeassistant')
    components = types.ModuleType('homeassistant.components')
    bluetooth = types.ModuleType('homeassistant.components.bluetooth')
    components.bluetooth = bluetooth
    light = types.ModuleType('homeassistant.components.light')
    class Entity:
        def async_write_ha_state(self):
            self.written = True
    light.LightEntity = Entity
    light.ColorMode = types.SimpleNamespace(COLOR_TEMP='color_temp', RGB='rgb')
    light.ATTR_BRIGHTNESS = 'brightness'
    light.ATTR_COLOR_TEMP_KELVIN = 'color_temp_kelvin'
    light.ATTR_RGB_COLOR = 'rgb_color'
    exceptions = types.ModuleType('homeassistant.exceptions')
    exceptions.HomeAssistantError = RuntimeError
    modules = {'oasis_adapter_test': package, 'homeassistant': ha,
               'homeassistant.components': components,
               'homeassistant.components.bluetooth': bluetooth,
               'homeassistant.components.light': light,
               'homeassistant.exceptions': exceptions}
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location('oasis_adapter_test.light', ROOT / 'light.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


LIGHT = load_light()


class LightAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.controller = types.SimpleNamespace(send=AsyncMock())
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

    async def test_conflicting_modes_rejected_before_transmit(self):
        with self.assertRaises(RuntimeError):
            await self.entity.async_turn_on(rgb_color=(0, 255, 0), color_temp_kelvin=6500)
        self.controller.send.assert_not_called()
