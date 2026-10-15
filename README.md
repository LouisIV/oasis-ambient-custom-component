# Oasis Ambient — local Bluetooth Mesh

Experimental Home Assistant custom integration. No lamp firmware changes or
factory reset. Source is maintained in the private GitHub repository
[LouisIV/oasis-ambient-custom-component](https://github.com/LouisIV/oasis-ambient-custom-component).
Not listed in the HACS catalog; add it as a custom repository using the
installation button below.

## Verified against a real lamp

OASIS_965bac, ambient_2_0, firmware 2.32.1: authenticated secure beacon;
encrypted Config Default TTL query and reply (7); OFF/ON; 1% brightness;
100% brightness at 6500 K. The owner visually confirmed the lighting changes.
Pure green was also physically verified after selecting color mode. Sending
RGB alone while in white mode produced no visible change. The integration
automatically selects color or white mode when the respective value is set.

The transport was physically verified from macOS. Home Assistant/Pi deployment
is under investigation; repeated control there is not yet verified (see below).
App-derived CCT range is 2700–6500 K; not every endpoint/value was physically
tested. The standalone temperature command is decoded but not separately
physically verified.

## Installation and setup

The integration can be installed through HACS or manually.

### With HACS

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

Add this repository as a [custom repository](https://hacs.xyz/docs/faq/custom_repositories/)
with category **Integration**, then install it and restart Home Assistant. You
can also open it directly in Home Assistant:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=LouisIV&repository=oasis-ambient-custom-component&category=integration)

### Manual installation

Copy `custom_components/oasis_ambient` into Home Assistant's
`/config/custom_components/`, then restart Home Assistant.

### Setup

1. Enable Home Assistant's Bluetooth integration. A connectable local adapter
   or active ESPHome Bluetooth proxy must be within range. The integration
   uses Home Assistant's Bluetooth device lookup, not an independent scanner.
2. Add **Oasis Ambient Local BLE** in Devices & services. Choose **Sign in to
   Oasis** and enter your Oasis email and password. Home Assistant retrieves
   your mesh configuration directly from Oasis. The integration does not save
   your password or account tokens.
3. Select your lamps. Home Assistant discovers a nearby proxy for each mesh,
   reserves a local controller address, and checks authenticated BLE connectivity
   without changing any lights or pairing. Proxy access does not prove that
   every selected destination lamp is online.
4. Each lamp appears as its own light entity. Lamps in the same network share
   a serialized connection queue and durable sequence counter. Separate mesh
   networks get independent credentials and counters. Commands always address
   the selected lamp, never a broadcast group.

Email/password login and mesh retrieval were verified on the owner’s account
in Home Assistant 2026.10.1 with integration 0.3.6. The lamp selection form
loaded OASIS_965bac successfully. BLE setup remains blocked by no reachable
matching mesh proxy; successful lamp control through this flow is not yet verified. Accounts requiring additional login
verification are not yet supported by this form. For those accounts or existing
exports, use **Advanced setup** → **Import a credential file**, or the
[desktop exporter](#export-credentials-on-your-computer).

Private mesh exports are stored with 0600 permissions under
`/config/.storage/oasis_ambient/`; sender reservation directories are 0700.
Daily lighting control is local and does not need an Oasis login or cloud API.
The config-flow implementation uses Home Assistant's native
[upload pattern](https://github.com/home-assistant/core/blob/2026.3.0/homeassistant/components/influxdb/config_flow.py)
and [progress steps](https://developers.home-assistant.io/docs/data_entry_flow_index/).

## Export credentials on your computer

Pair all lamps normally in the Oasis app first. Run this helper on a desktop
with a display, not a headless Raspberry Pi. From a checkout of this repository:

```sh
python3 -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell instead: .venv\Scripts\Activate.ps1
python -m pip install -r tools/requirements.txt
python -m playwright install chromium
python tools/export_credentials.py
```

The helper opens Oasis's official login page in an isolated browser window.
Sign in yourself, including any normal Apple/Google/MFA steps. It captures the
OAuth callback, retrieves all exported mesh networks, and saves
`oasis-credentials.json`. Upload that file in Home Assistant. Subsequent exports
can use `--output oasis-credentials-new.json`; existing files are never overwritten.

Passwords are entered only on the identity-provider page. The helper does not
read form fields, save browser sessions, or persist authorization codes or
account tokens. The final export DOES contain control keys: keep it private,
do not attach it to issues, and delete the desktop copy when no longer needed.
POSIX permissions are set to 0600; on Windows, store it in your private user
folder and apply the appropriate filesystem access restrictions.

Why a desktop helper? The Oasis public OAuth client redirects to its mobile
app's `rainmaker://` URL, not a Home Assistant callback. The helper observes
that redirect so users need not copy authorization codes out of developer tools.
This is not yet a packaged desktop app: Python/browser installation is still
required. Live provider login with this new helper and the full HA UI remain
to be tested; the earlier manual OAuth/key export worked against the real account.

## Add more lamps later

Open the integration's **Configure** menu and choose **Add lamps from saved
configuration**. Already configured lamps are hidden. Select additional nearby
lamps and connect; existing entity IDs, sender addresses, and counters remain
intact. If you recently paired new lamps in Oasis, choose **Sign in to Oasis**
to fetch the current configuration. Account tokens are not retained, so this
requires signing in again. File imports remain available under **Advanced
setup** after rerunning the exporter. One file can contain several mesh
networks, and several lamps can be selected in one pass.

If no proxy for a selected mesh is reachable, no entries from that selection
are added. Bring a proxy into range and retry. A failed or cancelled
setup may retain private credential files and sender reservations; reservations
are intentionally never recycled automatically. Existing v0.2 single-lamp
entries continue working and can use Configure to add more lamps.

## Important limits

- Light state is **optimistic** (`assumed_state`), not device-confirmed.
  Changes from the Oasis app/touch controls are not reflected automatically.
  A successful write means transmitted, not acknowledged by the light.
- RGB and white temperature are exposed. No effects, scenes, firmware updates,
  provisioning, or resets exposed.
- Multiple exported mesh networks are supported, each using NetKey0 and
  AppKey0, vendor model 02E5C00A on the first element. Other layouts fail validation.
- Discovery resolves current proxies by Mesh Network ID on every lookup,
  preferring the strongest signal with a live scanner backend. Saved Bluetooth
  addresses and unique lamp names are fallback hints; an address advertising
  another network is excluded. Mesh authentication still verifies the network
  keys before sending commands.
- Bluetooth proxy addresses can change without changing HA entity IDs. Mesh
  destination addresses are separate: they still come from imported credentials.
  Reprovisioning or swapping mesh destination addresses is not automatically
  reconciled. Discovery does not recover mesh keys or replace credential import.
- Automatic sender reservation excludes exported allocations and locally
  reserved addresses. Unrelated third-party controllers absent from the export
  cannot be discovered; do not run cloned or independently provisioned controllers
  using the same sender. Future Oasis provisioner allocations must not overlap
  locally reserved addresses.
- Mesh key refresh and IV update transitions fail closed rather than risking
  cryptographic nonce reuse. They require deliberate migration work.
- NEVER delete, roll back, or restore an old sequence database while reusing
  a sender address/key. After backup restoration or lost counters, reserve a
  fresh sender address and reconfigure. Keep old sender addresses retired.
- Do not copy a configured entry and counter database to a second live host.
- A phone's BLE inspection app can occupy the lamp connection; disconnect it.
- Connection establishment uses `bleak-retry-connector` supplied by Home
  Assistant's Bluetooth dependency. Retries happen before sending a batch;
  partially transmitted commands are never automatically replayed.
- Proxy discovery also matches the Mesh Network ID, so a missing advertised
  name or changed proxy address does not require reimporting credentials.
  A proxy on the same mesh may carry another lamp's addressed commands.
  A live scanner backend and authenticated secure beacon are still required;
  cached advertisement history alone is not treated as reachability.
- A successful HA service response alone is not proof of control: HA may skip
  unavailable entities. Check the entity state and logs, and verify the physical
  lamp. Connection failures now include the underlying exception in HA logs.

## Protocol

Proxy service 1828, Data In 2ADD, Data Out 2ADE. Managed-flooding Mesh Network
PDUs use AES-CCM, standard key derivation, privacy obfuscation, AppKey-bound
access messages, and durable sequence counters. Proxy SAR uses 20-byte GATT
values to work with a minimum MTU. Vendor company 02E5, model C00A.

Access PDUs (these are NOT directly writable GATT payloads):

| Function | Access bytes |
| --- | --- |
| Power | `C3 E5 02` + boolean byte |
| Brightness | `C4 E5 02` + percent byte + epoch seconds LE32 |
| White temperature | `C5 E5 02` + Kelvin LE16 |
| Combined white | `D2 E5 02` + Kelvin LE16 + percent byte + epoch milliseconds low32 LE |
| RGB | `C6 E5 02` + red, green, blue bytes |
| Select mode | `CC E5 02` + 01 for RGB, 02 for white |

Only unsegmented access messages (up to 11 bytes) are implemented. Commands
are serialized per mesh network; partial batches are not automatically replayed.

## Development validation

With Python, `bleak`, `cryptography`, and `voluptuous` installed, run:

```sh
python tests/run_protocol_tests.py
```

The tests cover standard mesh cryptography vectors, proxy segmentation,
durable counter allocation, restart behavior, setup without lighting writes,
command encoders, multi-lamp import/add flows, OAuth validation, and light-adapter
mode ordering/error behavior. Adapter
tests use explicit Home Assistant API doubles; they are not a full Home
Assistant runtime test. No real credentials are included in the project.

The APK receive path examined did not provide a verified lighting-state
query/status schema. Authenticated configuration readback (TTL=7) works, but
is not equivalent to power/brightness/color readback. State remains honestly
marked optimistic until such a protocol is verified.

### Home Assistant hardware validation status

Version 0.3.1 has been loaded on Home Assistant 2026.10.1 on a Raspberry Pi.
Credential import and authenticated mesh setup succeeded. Repeated control is
**not yet validated**: runtime diagnostics showed the lamp absent from the
Bluetooth backend's discovered devices, despite an older cached advertisement.
The adapter was scanning with all five connection slots free. An active-scan
test did not rediscover the lamp; the adapter's original automatic mode was
restored. Treat this release as experimental pending repeated physical tests.

Further investigation: one owner-approved software reboot restored proxy
advertisements without changing mesh address or keys. The next HA connection
failed because its discovered GATT table lacked characteristic 2ADE; the lamp
then became undiscoverable again. This does not establish the cause of the
radio disappearance. Version 0.3.3 disables the optional service-cache shortcut,
validates both proxy characteristics, and performs at most one cache refresh
before sending any commands. That recovery has regression coverage but still
needs live validation. The cloud `BLE Connected` flag remained true immediately
after reboot and must not be treated as proof of an active GATT connection.

A second approved software reboot increased Boot Count from 4 to 5 and briefly
restored discovery. The subsequent HA test failed; `meshRxCount` remained zero.
An availability callback timing issue was identified: entity state could be
updated before the scanner backend's device list. Version 0.3.4 schedules that
update on the next event-loop turn and logs service UUIDs on incomplete GATT
discovery. It is confirmed running on HA with no startup errors, but the lamp
is again absent from the Bluetooth backend. Neither this timing fix nor cache
recovery has been shown to restore reliable hardware control. A controlled
Mac-first versus Pi-first connection comparison is still needed to isolate the
failure; no factory reset or mesh reset has been performed.

Version 0.3.5 removes the integration's automatic cache-clear/reconnect after
incomplete GATT discovery. The upstream Linux cache-clear implementation can
issue BlueZ `RemoveDevice`, so this is not simply an in-memory refresh. Instead,
the integration logs service and characteristic UUIDs, fails before sending,
and disconnects normally. This preserves the original failure rather than
potentially replacing it with a missing-device error from the second attempt.
It is a diagnostic safety correction, not a demonstrated fix for the lamp's
disappearing advertisements. Connection-establishment retries remain managed
by Home Assistant's retry connector; application batches are never replayed.
