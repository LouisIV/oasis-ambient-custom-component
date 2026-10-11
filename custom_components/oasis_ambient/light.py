"""Local RGB and white-light controls; state is optimistic, not polled."""
from bleak.exc import BleakError
from homeassistant.components import bluetooth
from homeassistant.components.light import LightEntity, ColorMode, ATTR_BRIGHTNESS, ATTR_COLOR_TEMP_KELVIN, ATTR_RGB_COLOR
from homeassistant.exceptions import HomeAssistantError
from . import device_for
from .const import DOMAIN
from .protocol import oasis_commands as commands


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([OasisLight(entry, hass.data[DOMAIN][entry.entry_id])])


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

    def __init__(self, entry, controller):
        self.entry = entry
        self.controller = controller
        self._attr_unique_id = entry.unique_id
        self._attr_device_info = {'identifiers': {(DOMAIN, entry.unique_id)},
                                  'name': entry.data['lamp_name'], 'manufacturer': 'Oasis',
                                  'model': 'Ambient (Bluetooth Mesh)'}

    @property
    def available(self):
        return device_for(self.hass, self.entry.data['address']) is not None

    async def async_added_to_hass(self):
        self.async_on_remove(bluetooth.async_register_callback(
            self.hass, lambda *_: self.async_write_ha_state(),
            {'address': self.entry.data['address'], 'connectable': True},
            bluetooth.BluetoothScanningMode.ACTIVE))
        self.async_on_remove(bluetooth.async_track_unavailable(
            self.hass, lambda *_: self.async_write_ha_state(),
            self.entry.data['address'], connectable=True))

    async def _send(self, messages):
        device = device_for(self.hass, self.entry.data['address'])
        if device is None:
            raise HomeAssistantError('Lamp is not reachable through Home Assistant Bluetooth')
        try:
            await self.controller.send(device, messages)
        except (BleakError, TimeoutError, OSError, ValueError) as error:
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
