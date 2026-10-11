"""Local-only Oasis Ambient integration."""
import json
from pathlib import Path

from homeassistant.components import bluetooth
from homeassistant.exceptions import ConfigEntryError
from .const import DOMAIN
from .protocol.oasis_controller import OasisController


def load_controller(data):
    mesh = json.loads(Path(data['mesh_file']).read_text())
    return OasisController(mesh, data['lamp_name'], data['source'], data['sequence_file'])


def device_for(hass, address):
    return bluetooth.async_ble_device_from_address(hass, address, connectable=True)


async def async_setup_entry(hass, entry):
    try:
        controller = await hass.async_add_executor_job(load_controller, entry.data)
        if not await hass.async_add_executor_job(controller.sequence_path.exists):
            raise ValueError('Sequence state missing; do not reuse this sender address')
    except (OSError, ValueError, KeyError, StopIteration) as error:
        raise ConfigEntryError('Invalid mesh export or missing sender state; see setup documentation') from error
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controller
    await hass.config_entries.async_forward_entry_setups(entry, ['light'])
    return True


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, ['light']):
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return True
    return False
