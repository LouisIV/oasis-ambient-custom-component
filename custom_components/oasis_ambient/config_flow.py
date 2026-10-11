"""Import existing mesh keys; never reset or provision a lamp."""
import hashlib
from pathlib import Path
import voluptuous as vol
from bleak.exc import BleakError
from homeassistant import config_entries
from homeassistant.components import bluetooth
from . import device_for, load_controller
from .const import DOMAIN


class OasisConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 2

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            data = dict(user_input)
            if not data.pop('new_sender_confirmed', False):
                errors['base'] = 'confirm_sender'
            else:
                device = device_for(self.hass, data['address'])
                if device is None:
                    errors['base'] = 'not_found'
                else:
                    try:
                        # Stable path per address reservation: removing an entry must
                        # never cause its cryptographic counter to be reset.
                        directory = Path(self.hass.config.path('.storage', DOMAIN))
                        await self.hass.async_add_executor_job(lambda: directory.mkdir(mode=0o700, parents=True, exist_ok=True))
                        data['sequence_file'] = str(directory / 'unused')
                        controller = await self.hass.async_add_executor_job(load_controller, data)
                        identity = hashlib.sha256((controller.identity + ':' + str(data['source'])).encode()).hexdigest()[:24]
                        data['sequence_file'] = str(directory / f'{identity}.db')
                        controller.sequence_path = Path(data['sequence_file'])
                        await self.async_set_unique_id(f'{controller.identity}:{controller.destination:04x}')
                        self._abort_if_unique_id_configured()
                        await controller.send(device, [], initialize_sender=True)
                        return self.async_create_entry(title=data['lamp_name'], data=data)
                    except (OSError, ValueError, KeyError, StopIteration):
                        errors['base'] = 'invalid_mesh'
                    except (BleakError, TimeoutError):
                        errors['base'] = 'cannot_connect'
        return self.async_show_form(step_id='user', errors=errors, data_schema=vol.Schema({
            vol.Required('mesh_file'): str,
            vol.Required('lamp_name', default='OASIS_965bac'): str,
            vol.Required('address'): str,
            vol.Required('source', default=32766): vol.All(vol.Coerce(int), vol.Range(min=1, max=32767)),
            vol.Required('new_sender_confirmed', default=False): bool,
        }))
