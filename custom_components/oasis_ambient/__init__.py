"""Local-only Oasis Ambient integration."""
import json
import asyncio
from pathlib import Path

from homeassistant.components import bluetooth
from homeassistant.exceptions import ConfigEntryError
from .const import DOMAIN
from .protocol.oasis_controller import OasisController


def load_controller(data, lock=None):
    mesh = json.loads(Path(data['mesh_file']).read_text())
    return OasisController(mesh, data['lamp_name'], data['source'], data['sequence_file'],
                           destination=data.get('destination'), lock=lock)


def lamp_data(entry):
    """Keep version-2 single-lamp entries compatible without changing IDs."""
    if 'lamps' in entry.data:
        return entry.data['lamps']
    return [dict(entry.data, unique_id=entry.unique_id)]


def device_for(hass, address):
    return bluetooth.async_ble_device_from_address(hass, address, connectable=True)


def network_lock(hass, identity):
    locks = hass.data.setdefault(DOMAIN, {}).setdefault('_network_locks', {})
    return locks.setdefault(identity, asyncio.Lock())


async def async_setup_entry(hass, entry):
    controllers = []
    try:
        for data in lamp_data(entry):
            # All destinations in a mesh share one radio-operation queue.
            lock = network_lock(hass, data['unique_id'].rsplit(':', 1)[0])
            controller = await hass.async_add_executor_job(load_controller, data, lock)
            if not await hass.async_add_executor_job(controller.sequence_path.exists):
                raise ValueError('Sequence state missing; do not reuse this sender address')
            controllers.append((data, controller))
    except (OSError, ValueError, KeyError, StopIteration) as error:
        raise ConfigEntryError('Invalid mesh export or missing sender state; see setup documentation') from error
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = controllers
    await hass.config_entries.async_forward_entry_setups(entry, ['light'])
    return True


async def async_unload_entry(hass, entry):
    if await hass.config_entries.async_unload_platforms(entry, ['light']):
        hass.data[DOMAIN].pop(entry.entry_id, None)
        return True
    return False
