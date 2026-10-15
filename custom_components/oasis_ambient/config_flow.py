"""Sign in once, select lamps, and authenticate locally; never reset lamps."""
from pathlib import Path
import secrets
import voluptuous as vol
from bleak.exc import BleakError
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.file_upload import process_uploaded_file
from homeassistant.core import callback
from homeassistant.helpers.selector import (FileSelector, FileSelectorConfig,
    NumberSelector, NumberSelectorConfig, SelectSelector, SelectSelectorConfig,
    TextSelector, TextSelectorConfig)
from . import device_for, lamp_data, network_lock
from .cloud import AccountError, fetch_account_meshes, restart_account_lamp
from .const import CONF_MODE_SETTLE_DELAY, DEFAULT_MODE_SETTLE_DELAY, DOMAIN
from .onboarding import MAX_EXPORT_BYTES, lamp_choices, mesh_identity, parse_export, reserve_sender, save_mesh
from .protocol.oasis_controller import OasisController


class OnboardingSteps:
    """Shared first-run and add-lamps flow. Secret material never enters forms."""

    def _start(self, entry=None):
        self._entry = entry
        self._meshes = {}
        self._loaded = False
        self._pending = {}
        self._connect_task = None
        self._error = None
        self._selected = []
        self._recovery_lamps = {}

    async def _load_saved(self):
        if self._loaded:
            return
        if self._entry is not None:
            for path in {x['mesh_file'] for x in lamp_data(self._entry)}:
                raw = await self.hass.async_add_executor_job(Path(path).read_bytes)
                for mesh in parse_export(raw):
                    self._meshes[mesh_identity(mesh)] = mesh
        self._loaded = True

    async def async_step_export(self, user_input=None):
        if user_input is not None:
            return await self.async_step_upload()
        return self.async_show_form(step_id='export', data_schema=vol.Schema({}))

    def _merge_meshes(self, imported):
        for mesh in imported:
            key = mesh_identity(mesh)
            for existing in self._meshes.values():
                if existing['meshUUID'] == mesh['meshUUID'] and (
                    mesh_identity(existing) != key or existing['appKeys'] != mesh['appKeys']
                ):
                    raise ValueError('Key migration is not supported')
        for mesh in imported:
            self._meshes[mesh_identity(mesh)] = mesh

    async def async_step_login(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self._load_saved()
                imported = await self.hass.async_add_executor_job(
                    fetch_account_meshes, user_input['email'], user_input['password'])
                self._merge_meshes(imported)
                if not lamp_choices(list(self._meshes.values())):
                    errors['base'] = 'no_lamps'
                else:
                    return await self.async_step_lamps()
            except AccountError as error:
                errors['base'] = error.code
            except (OSError, ValueError, KeyError, TypeError, StopIteration):
                errors['base'] = 'invalid_export'
        # Do not retain the submitted password, even as a form default.
        return self.async_show_form(step_id='login', errors=errors, data_schema=vol.Schema({
            vol.Required('email'): TextSelector(TextSelectorConfig(type='email')),
            vol.Required('password'): TextSelector(TextSelectorConfig(type='password')),
        }))

    async def async_step_advanced(self, user_input=None):
        return self.async_show_menu(step_id='advanced', menu_options=['upload', 'export'])

    async def async_step_upload(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self._load_saved()
                def read_upload():
                    with process_uploaded_file(self.hass, user_input['credential_file']) as path:
                        with path.open('rb') as stream:
                            return parse_export(stream.read(MAX_EXPORT_BYTES + 1))
                imported = await self.hass.async_add_executor_job(read_upload)
                self._merge_meshes(imported)
                if not lamp_choices(list(self._meshes.values())):
                    errors['base'] = 'no_lamps'
                else:
                    return await self.async_step_lamps()
            except (OSError, ValueError, KeyError, TypeError, StopIteration):
                errors['base'] = 'invalid_export'
        return self.async_show_form(step_id='upload', errors=errors, data_schema=vol.Schema({
            vol.Required('credential_file'): FileSelector(FileSelectorConfig(accept='.json')),
        }))

    def _configured(self):
        return {item['unique_id'] for entry in self.hass.config_entries.async_entries(DOMAIN)
                for item in lamp_data(entry) if item.get('unique_id')}

    def _nearby(self, name, mesh=None):
        key = None
        if mesh is not None:
            key = bytes.fromhex(next(k['key'] for k in mesh['netKeys'] if k['index'] == 0))
            if device := device_for(self.hass, None, key):
                return device.address
        matches = {info.address for info in bluetooth.async_discovered_service_info(self.hass, connectable=True)
                   if info.name == name}
        if len(matches) == 1:
            address = next(iter(matches))
            if device := device_for(self.hass, address, key):
                return device.address
        return None

    async def async_step_lamps(self, user_input=None):
        errors = {'base': self._error} if self._error else {}
        self._error = None
        try:
            await self._load_saved()
        except (OSError, ValueError, KeyError, TypeError):
            return await self.async_step_upload()
        choices = {key: value for key, value in lamp_choices(list(self._meshes.values())).items()
                   if key not in self._configured()}
        if not choices:
            return self.async_show_form(step_id='no_new_lamps', data_schema=vol.Schema({}))
        if user_input is not None:
            selected = list(dict.fromkeys(user_input.get('lamps', [])))
            if not selected or any(key not in choices for key in selected):
                errors['base'] = 'select_lamps'
            elif any(self._nearby(choices[key][1]['name'], choices[key][0]) is None for key in selected):
                # Cloud restart is still available when discovery is the part
                # that failed; do not require a live proxy for that recovery.
                self._selected = selected
                self._recovery_lamps = choices
                self._error = 'not_nearby'
                return await self.async_step_recovery()
            else:
                self._selected = selected
                self._recovery_lamps = choices
                self._connect_task = self.hass.async_create_task(self._connect_selected(selected, choices))
                return await self.async_step_connect()
        options = [{'value': key, 'label': f"{node['name']} — {'mesh proxy nearby' if self._nearby(node['name'], mesh) else 'not found nearby'}"}
                   for key, (mesh, node) in choices.items()]
        return self.async_show_form(step_id='lamps', errors=errors, data_schema=vol.Schema({
            vol.Required('lamps'): SelectSelector(SelectSelectorConfig(options=options, multiple=True)),
        }))

    async def async_step_connect(self, user_input=None):
        if self._connect_task is None:
            return await self.async_step_lamps()
        if not self._connect_task.done():
            return self.async_show_progress(step_id='connect', progress_action='connect_lamps',
                                            progress_task=self._connect_task)
        return self.async_show_progress_done(next_step_id='finish')

    async def async_step_finish(self, user_input=None):
        if self._connect_task is None:
            return await self.async_step_lamps()
        try:
            added = self._connect_task.result()
        except (BleakError, TimeoutError):
            self._error = 'cannot_connect'
        except (OSError, ValueError, KeyError, TypeError, StopIteration):
            self._error = 'unsafe_mesh'
        finally:
            self._connect_task = None
        if self._error:
            if self._error == 'cannot_connect':
                self._recovery_lamps = choices
                return await self.async_step_recovery()
            return await self.async_step_lamps()
        if any(item['unique_id'] in self._configured() for item in added):
            self._error = 'already_added'
            return await self.async_step_lamps()
        if self._entry is None:
            return self.async_create_entry(title='Oasis Ambient', data={'lamps': added})
        existing = lamp_data(self._entry)
        self.hass.config_entries.async_update_entry(self._entry, data={'lamps': existing + added})
        await self.hass.config_entries.async_reload(self._entry.entry_id)
        return self.async_create_entry(title='', data={})

    async def async_step_recovery(self, user_input=None):
        """Offer one explicit recovery action after Bluetooth setup fails."""
        return self.async_show_menu(step_id='recovery',
                                    menu_options=['retry', 'software_reset'])

    async def async_step_retry(self, user_input=None):
        self._error = None
        return await self.async_step_lamps()

    async def async_step_software_reset(self, user_input=None):
        choices = {key: value for key, value in self._recovery_lamps.items()
                   if key in self._selected}
        if user_input is not None:
            selected = user_input.get('lamp')
            if selected not in choices:
                return self.async_show_form(step_id='software_reset',
                                            errors={'base': 'select_lamp'},
                                            data_schema=self._reset_schema(choices))
            self._reset_lamp = choices[selected][1]
            return await self.async_step_reset_login()
        return self.async_show_form(step_id='software_reset',
                                    data_schema=self._reset_schema(choices))

    @staticmethod
    def _reset_schema(choices):
        return vol.Schema({vol.Required('lamp'): SelectSelector(SelectSelectorConfig(
            options=[{'value': key, 'label': node['name']}
                     for key, (_, node) in choices.items()]))})

    async def async_step_reset_login(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                await self.hass.async_add_executor_job(
                    restart_account_lamp, user_input['email'], user_input['password'],
                    self._reset_lamp['name'], self._reset_lamp['unicastAddress'])
                return await self.async_step_reset_done()
            except AccountError as error:
                errors['base'] = error.code
            except (OSError, ValueError, KeyError, TypeError, StopIteration):
                errors['base'] = 'restart_failed'
        return self.async_show_form(step_id='reset_login', errors=errors, data_schema=vol.Schema({
            vol.Required('email'): TextSelector(TextSelectorConfig(type='email')),
            vol.Required('password'): TextSelector(TextSelectorConfig(type='password')),
        }))

    async def async_step_reset_done(self, user_input=None):
        return self.async_show_menu(step_id='reset_done', menu_options=['retry'])

    async def async_step_no_new_lamps(self, user_input=None):
        return await self.async_step_upload()

    async def _connect_selected(self, selected, choices):
        root = Path(self.hass.config.path('.storage', DOMAIN))
        existing_networks = {}
        for entry in self.hass.config_entries.async_entries(DOMAIN):
            for item in lamp_data(entry):
                existing_networks[item['unique_id'].rsplit(':', 1)[0]] = item
        added = []
        for unique_id in selected:
            mesh, node = choices[unique_id]
            identity = mesh_identity(mesh)
            if identity not in self._pending:
                previous = existing_networks.get(identity)
                if previous:
                    seqfile = Path(previous['sequence_file'])
                    if not await self.hass.async_add_executor_job(seqfile.exists):
                        raise ValueError('Existing sender counter missing')
                    source, directory = previous['source'], seqfile.parent
                    initialize = False
                else:
                    source, directory = await self.hass.async_add_executor_job(reserve_sender, mesh, root)
                    seqfile = directory / 'sequence.db'
                    initialize = True
                meshfile = directory / f'mesh-{secrets.token_hex(12)}.json'
                self._pending[identity] = {'source': source, 'sequence_file': str(seqfile),
                                           'mesh_file': str(meshfile), 'initialize': initialize,
                                           'saved': False}
            reservation = self._pending[identity]
            address = self._nearby(node['name'], mesh)
            device = device_for(self.hass, address) if address else None
            if device is None:
                raise ValueError('Device no longer reachable')
            destination = int(node['unicastAddress'], 16)
            controller = OasisController(mesh, node['name'], reservation['source'],
                                         reservation['sequence_file'], destination=destination,
                                         lock=network_lock(self.hass, identity))
            await controller.send(device, [], initialize_sender=reservation['initialize'], authenticate_only=True)
            reservation['initialize'] = False
            if not reservation['saved']:
                await self.hass.async_add_executor_job(save_mesh, mesh, reservation['mesh_file'])
                reservation['saved'] = True
            added.append({key: reservation[key] for key in ('source', 'sequence_file', 'mesh_file')} | {
                'unique_id': unique_id, 'lamp_name': node['name'], 'address': address,
                'destination': destination,
            })
        return added


class OasisConfigFlow(OnboardingSteps, config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    def __init__(self):
        self._start()

    async def async_step_bluetooth(self, discovery_info):
        """Handle discovery of a nearby Bluetooth Mesh Proxy."""
        # Discovery is only a prompt to start setup. The proxy advertisement
        # does not contain enough information to identify an Oasis account or
        # a lamp, so never create an entry from Bluetooth alone.
        self._discovery_info = discovery_info
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        return self.async_show_menu(step_id='user', menu_options=['login', 'advanced'])

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OasisOptionsFlow(config_entry)


class OasisOptionsFlow(OnboardingSteps, config_entries.OptionsFlow):
    def __init__(self, entry):
        self._start(entry)

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(step_id='init', menu_options=['settings', 'lamps', 'login', 'advanced'])

    async def async_step_settings(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title='', data=user_input)
        return self.async_show_form(step_id='settings', data_schema=vol.Schema({
            vol.Required(CONF_MODE_SETTLE_DELAY,
                         default=getattr(self.config_entry, 'options', {}).get(CONF_MODE_SETTLE_DELAY,
                                                               DEFAULT_MODE_SETTLE_DELAY)):
                NumberSelector(NumberSelectorConfig(min=0, max=5, step=0.05, mode='box')),
        }))
