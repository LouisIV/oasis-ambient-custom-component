"""Local RGB and white-light controls; state is optimistic, not polled."""
import asyncio
import logging
from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.components.light import LightEntity, ColorMode, ATTR_BRIGHTNESS, ATTR_COLOR_TEMP_KELVIN, ATTR_RGB_COLOR
from homeassistant.exceptions import HomeAssistantError
from . import device_for
from .const import DOMAIN
from .protocol.oasis_controller import IncompleteProxyDiscovery
from .protocol import oasis_commands as commands

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([OasisLight(entry, controller, data)
                        for data, controller in hass.data[DOMAIN][entry.entry_id]])


class OasisLight(LightEntity):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_assumed_state = True
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.RGB}
    _attr_color_mode = ColorMode.COLOR_TEMP
    _attr_min_color_temp_kelvin = 2700
    _attr_max_color_temp_kelvin = 6500
    _attr_is_on = None
    _attr_brightness = None
    _attr_color_temp_kelvin = None
    _attr_rgb_color = None

    def __init__(self, entry, controller, data=None):
        self.entry = entry
        self.data = data if data is not None else entry.data
        self.controller = controller
        self._attr_unique_id = self.data.get('unique_id', entry.unique_id)
        self._attr_device_info = {'identifiers': {(DOMAIN, self._attr_unique_id)},
                                  'name': self.data['lamp_name'], 'manufacturer': 'Oasis',
                                  'model': 'Ambient (Bluetooth Mesh)'}

    @property
    def available(self):
        return device_for(self.hass, self.data['address'], self.controller.net_key) is not None

    def _bluetooth_changed(self, *_):
        # Scanner callbacks may run before the live backend device list is
        # updated. Recompute availability on the next event-loop iteration.
        self.async_schedule_update_ha_state()

    async def async_added_to_hass(self):
        self.async_on_remove(bluetooth.async_register_callback(
            self.hass, self._bluetooth_changed,
            {'address': self.data['address'], 'connectable': True},
            bluetooth.BluetoothScanningMode.ACTIVE))
        self.async_on_remove(bluetooth.async_register_callback(
            self.hass, self._bluetooth_changed,
            {'service_uuid': '00001828-0000-1000-8000-00805f9b34fb', 'connectable': True},
            bluetooth.BluetoothScanningMode.PASSIVE))
        self.async_on_remove(bluetooth.async_track_unavailable(
            self.hass, self._bluetooth_changed,
            self.data['address'], connectable=True))

    async def _send(self, messages):
        # A BlueZ cache refresh removes the old BLEDevice. Give the scanner a
        # bounded window to publish the replacement address, then resolve it
        # again. Only incomplete discovery is retried: a failure after the
        # first write could have partially transmitted the batch.
        deadline = asyncio.get_running_loop().time() + 15
        cache_recovery_used = False
        while True:
            device = device_for(self.hass, self.data['address'], self.controller.net_key)
            if device is None:
                if asyncio.get_running_loop().time() >= deadline:
                    raise HomeAssistantError('Lamp is not reachable through Home Assistant Bluetooth')
                await asyncio.sleep(1)
                continue
            try:
                await self.controller.send(device, messages)
                return
            except IncompleteProxyDiscovery as error:
                if cache_recovery_used or asyncio.get_running_loop().time() >= deadline:
                    _LOGGER.exception('Oasis BLE operation failed for %s', self.data['address'])
                    raise HomeAssistantError('Oasis BLE command failed; state not confirmed') from error
                cache_recovery_used = True
                _LOGGER.warning('Oasis proxy discovery was incomplete for %s; '
                                'waiting for Bluetooth rediscovery before retrying',
                                self.data['address'])
                await asyncio.sleep(2)
            except (BleakError, TimeoutError, OSError, ValueError) as error:
                _LOGGER.exception('Oasis BLE operation failed for %s', self.data['address'])
                raise HomeAssistantError('Oasis BLE command failed; state not confirmed') from error

    async def async_turn_on(self, **kwargs):
        level = kwargs.get(ATTR_BRIGHTNESS)
        kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        rgb = kwargs.get(ATTR_RGB_COLOR)
        if rgb is not None and kelvin is not None:
            raise HomeAssistantError('Choose either RGB or white temperature, not both')
        if level == 0:
            await self.async_turn_off()
            return
        percent = max(1, min(100, round(level * 100 / 255))) if level is not None else None
        messages = []
        if rgb is not None:
            messages.extend([commands.color_mode(True), commands.rgb(*rgb)])
        if kelvin is not None:
            messages.append(commands.color_mode(False))
        if percent is not None and kelvin is not None:
            messages.append(commands.brightness_temperature(percent, kelvin))
        elif percent is not None:
            messages.append(commands.brightness(percent))
        elif kelvin is not None:
            messages.append(commands.temperature(kelvin))
        messages.append(commands.power(True))
        await self._send(messages)
        self._attr_is_on = True
        if percent is not None:
            self._attr_brightness = round(percent * 255 / 100)
        if kelvin is not None:
            self._attr_color_temp_kelvin = kelvin
            self._attr_color_mode = ColorMode.COLOR_TEMP
        elif rgb is not None:
            self._attr_rgb_color = tuple(rgb)
            self._attr_color_mode = ColorMode.RGB
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self._send([commands.power(False)])
        self._attr_is_on = False
        self.async_write_ha_state()
