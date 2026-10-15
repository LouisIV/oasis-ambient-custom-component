# Changelog

All notable changes to this project are documented here.

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
