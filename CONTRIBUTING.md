# Contributing

Thanks for helping improve Oasis Ambient. This is an experimental Home
Assistant integration, so changes that affect Bluetooth transport, mesh
cryptography, credential handling, or sequence counters need extra care.

## Before opening a pull request

- Explain the user-visible problem and the approach taken.
- Add or update focused tests for protocol, onboarding, or light behavior.
- Run `python tests/run_protocol_tests.py` with the development dependencies
  installed.
- Do not include credentials, mesh exports, account tokens, private keys, or
  device-identifying logs. Use the public sample vectors in `tests/`.
- Document any hardware, Home Assistant, Python, or Bluetooth proxy versions
  used for validation.

Keep changes small when possible. A pull request that changes the wire
protocol should include the observation or specification that supports it.

## Development setup

The protocol tests need Python packages including `cryptography`, `bleak`, and
`voluptuous`; the Home Assistant adapter tests additionally need Home Assistant
itself. The desktop credential exporter has separate requirements in
`tools/requirements.txt`.

## Pull requests

Open a pull request against `main` with a clear summary, test results, and
known limitations. Maintainers may request a reproducible trace or a hardware
test before merging Bluetooth changes.

## Releases

For a release, update the integration version in `manifest.json`, add a dated
entry to `CHANGELOG.md`, run the available checks, and create an annotated tag
such as `v0.3.6`. Publish the matching GitHub release with the changelog entry.
