# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Fixed

- Resolve the current mesh proxy after acquiring the shared command queue so
  queued commands do not connect using a stale discovery result.
- Use validated service caching and retry an incomplete GATT service table once after a normal disconnect,
  before mesh writes. Never remove the BlueZ device or replay a command after a write failure.
  This addresses a reproduced Pi discovery failure. A two-hour live run passed
  repeated commands, a 15-minute idle reconnect, and Adaptive Lighting.
  A later manual brightness adjustment exposed a stale notification handle;
  notification setup now shares the bounded fresh-discovery retry before writes.
  That follow-up remains under hardware validation, and a separate mixed RGB/white
  request is being investigated. See `research/reliability-validation.json`.

- Recheck Bluetooth availability every 30 seconds from Home Assistant's live
  discovery cache, without connecting or sending commands, so missed callbacks
  do not leave a rediscovered lamp stuck unavailable.

- Removed automatic Bluetooth cache removal and reconnect from the light-control
  error handler. It was still running after incomplete GATT discovery despite
  the transport's fail-without-recovery behavior. Failed commands now preserve
  the original error and leave optimistic light state unchanged. Hardware
  validation is still needed; this is not a confirmed fix for app crashes or
  disappearing lamp advertisements.

## [0.3.6] - 2026-10-15

This is an experimental public beta. Home Assistant/Pi control through a
Bluetooth proxy remains hardware-dependent and is not broadly validated.

### Added

- HACS custom-repository installation guidance and Home Assistant redirect.
- Oasis account sign-in and dynamic mesh-proxy discovery by Mesh Network ID.
- Multi-lamp selection, saved-configuration onboarding, and add-lamps flow.
- Configurable mode-settle delay.
- Safer sender reservation and durable per-network sequence handling.
- MIT licensing, contribution guidance, support guidance, and issue forms.

### Verified

- Protocol test vectors and adapter tests using explicit Home Assistant doubles.
- Source compilation on Python 3.14.2.
- Email/password mesh retrieval and lamp-selection UI on Home Assistant 2026.10.1.
- Physical command transport from macOS against an OASIS_965bac / ambient_2_0
  lamp running firmware 2.32.1.

### Known limitations

- Repeated physical control from Home Assistant on Raspberry Pi/Bluetooth proxy
  is not yet verified.
- State is optimistic; power, brightness, RGB, and temperature are not
  device-confirmed.
- Accounts requiring additional login verification are not supported by the
  in-Home-Assistant sign-in form; use the desktop exporter or credential import.
