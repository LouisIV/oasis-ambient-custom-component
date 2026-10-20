"""Local-only Oasis Ambient integration."""
import json
import asyncio
from pathlib import Path

from homeassistant.components import bluetooth
from homeassistant.exceptions import ConfigEntryError
from .const import CONF_MODE_SETTLE_DELAY, DEFAULT_MODE_SETTLE_DELAY, DOMAIN
from .protocol.oasis_controller import OasisController
from .protocol.mesh_crypto import k3


def load_controller(data, lock=None, options=None):
    options = options or {}
    mesh = json.loads(Path(data['mesh_file']).read_text())
    return OasisController(mesh, data['lamp_name'], data['source'], data['sequence_file'],
                           destination=data.get('destination'), lock=lock,
                           mode_settle_delay=options.get(CONF_MODE_SETTLE_DELAY,
                                                         DEFAULT_MODE_SETTLE_DELAY))


def lamp_data(entry):
    """Keep version-2 single-lamp entries compatible without changing IDs."""
    if 'lamps' in entry.data:
        return entry.data['lamps']
    return [dict(entry.data, unique_id=entry.unique_id)]


def device_for(hass, address, net_key=None, *, network_only=False):
    """Resolve a current proxy, not just a cached name or historical MAC.

    A proxy for the same mesh can transport commands for any destination in
    that mesh. The controller still authenticates its secure beacon before
    allocating a sequence or sending a command.
    """
    addresses = []
    conflicting_addresses = set()
    if net_key is not None:
        network_id = b'\x00' + k3(net_key)
        discovered = bluetooth.async_discovered_service_info(hass, connectable=True)
        candidates = [info for info in discovered
                      if getattr(info, 'service_data', {}).get(
                          '00001828-0000-1000-8000-00805f9b34fb') == network_id]
        for info in discovered:
            advertised = getattr(info, 'service_data', {}).get(
                '00001828-0000-1000-8000-00805f9b34fb', b'')
            if len(advertised) == 9 and advertised[0] == 0 and advertised != network_id:
                conflicting_addresses.add(info.address)
        candidates.sort(key=lambda info: getattr(info, 'rssi', -127), reverse=True)
        addresses.extend(info.address for info in candidates if info.address not in addresses)
    # A saved address is only a fallback hint. It may now belong to another
    # network; never prefer it over current network-matching advertisements.
    if not network_only and address and address not in addresses and address not in conflicting_addresses:
        addresses.append(address)
    for candidate in addresses:
        # History can retain a BLEDevice after BlueZ has removed it. Such a
        # device makes the UI look available but cannot establish a connection.
        if not bluetooth.async_scanner_devices_by_address(hass, candidate, connectable=True):
            continue
        if device := bluetooth.async_ble_device_from_address(hass, candidate, connectable=True):
            return device
    return None


def network_proxy_for(hass, net_key):
    """Resolve only a currently advertised proxy for this mesh."""
    return device_for(hass, None, net_key, network_only=True)


def network_lock(hass, identity):
    locks = hass.data.setdefault(DOMAIN, {}).setdefault('_network_locks', {})
    return locks.setdefault(identity, asyncio.Lock())


async def async_setup_entry(hass, entry):
    controllers = []
    try:
        for data in lamp_data(entry):
            # All destinations in a mesh share one radio-operation queue.
            lock = network_lock(hass, data['unique_id'].rsplit(':', 1)[0])
            controller = await hass.async_add_executor_job(load_controller, data, lock, entry.options)
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
