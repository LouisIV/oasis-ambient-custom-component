# Oasis Ambient — local Bluetooth Mesh

Experimental Home Assistant custom integration. No lamp firmware changes or
factory reset. Not yet published to a GitHub repository or the HACS catalog.
The folder structure is suitable for a future HACS custom repository.

## Verified against a real lamp

OASIS_965bac, ambient_2_0, firmware 2.32.1: authenticated secure beacon;
encrypted Config Default TTL query and reply (7); OFF/ON; 1% brightness;
100% brightness at 6500 K. The owner visually confirmed the lighting changes.
Pure green was also physically verified after selecting color mode. Sending
RGB alone while in white mode produced no visible change. The integration
automatically selects color or white mode when the respective value is set.

The transport was exercised from macOS. Home Assistant/Pi deployment has not
been tested because the owner's Home Assistant instance is not running.
App-derived CCT range is 2700–6500 K; not every endpoint/value was physically
tested. The standalone temperature command is decoded but not separately
physically verified.

## Installation and setup

1. Copy `custom_components/oasis_ambient` into Home Assistant's
   `/config/custom_components/`, then restart Home Assistant.
2. Enable Home Assistant's Bluetooth integration. A connectable local adapter
   or active ESPHome Bluetooth proxy must be within range. The integration
   uses Home Assistant's Bluetooth device lookup, not an independent scanner.
3. Securely copy your existing private Nordic-format `mesh-export.json` to
   `/config/oasis-private/mesh-export.json`. Limit directory access to the
   Home Assistant user and file permissions to 0600. This file contains keys
   granting control of your mesh. Do not commit, share, or paste it into logs.
4. Add **Oasis Ambient Local BLE** in Devices & services. Enter the export
   path, exact lamp name, and Bluetooth address seen by Home Assistant. The
   macOS CoreBluetooth UUID is NOT the Bluetooth address on your Pi.
5. Reserve a unique sender address. Decimal 32766 (0x7ffe) is suggested for
   this Pi; the Mac experiments used 32767 (0x7fff). Setup rejects addresses
   belonging to exported nodes or provisioner ranges. It cannot detect other
   independently created controllers, so you must confirm the reservation.
6. Setup connects and authenticates the lamp's beacon without changing its
   light or pairing. It creates durable sequence storage under
   `/config/.storage/oasis_ambient/`. Normal operation never creates missing
   sequence state automatically.

Keys were obtained from an owner-authorized Oasis account export. Runtime
commands do not use Oasis cloud or store account passwords. Automated account
login/export is not included in this first integration; import the existing
export rather than attempting to pair/reset the lamp.

## Important limits

- Light state is **optimistic** (`assumed_state`), not device-confirmed.
  Changes from the Oasis app/touch controls are not reflected automatically.
  A successful write means transmitted, not acknowledged by the light.
- RGB and white temperature are exposed. No effects, scenes, firmware updates,
  provisioning, or resets exposed.
- One export/subnet using NetKey0 and AppKey0, vendor model 02E5C00A on the
  first element. Unsupported mesh layouts fail validation.
- Mesh key refresh and IV update transitions fail closed rather than risking
  cryptographic nonce reuse. They require deliberate migration work.
- NEVER delete, roll back, or restore an old sequence database while reusing
  a sender address/key. After backup restoration or lost counters, reserve a
  fresh sender address and reconfigure. Keep old sender addresses retired.
- Do not copy a configured entry and counter database to a second live host.
- A phone's BLE inspection app can occupy the lamp connection; disconnect it.

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
are serialized per controller; partial batches are not automatically replayed.

## Development validation

With Python, `bleak`, and `cryptography` installed, run:

```sh
python tests/run_protocol_tests.py
```

36 tests cover standard mesh cryptography vectors, proxy segmentation,
durable counter allocation, restart behavior, setup without lighting writes,
command encoders, and light-adapter mode ordering/error behavior. Adapter
tests use explicit Home Assistant API doubles; they are not a full Home
Assistant runtime test. No real credentials are included in the project.

The APK receive path examined did not provide a verified lighting-state
query/status schema. Authenticated configuration readback (TTL=7) works, but
is not equivalent to power/brightness/color readback. State remains honestly
marked optimistic until such a protocol is verified.
