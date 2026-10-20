# Discovery and setup investigation

Investigated October 14, 2026. Address rotation remains a hypothesis for Oasis,
not an observed explanation for the lamp disappearing.

## Evidence and distinctions

- `ble-research/ttl-query-observation.json` records an authenticated response
  from mesh source `0002`. The README's prior reboot investigation reports no
  change in mesh address or keys. Neither establishes lifetime stability.
- `ble-research/evidence.json` records a Mac-local CoreBluetooth UUID. This is
  not a BLE MAC address and cannot be compared directly with a Pi address.
  [Bleak documents this platform distinction](https://bleak.readthedocs.io/en/develop/backends/macos.html).
- Mesh unicast addresses are provisioning state, not ordinary rotating BLE
  discovery identifiers. Mesh 1.1 supports deliberate Node Address Refresh,
  which changes both unicast address and device key. Oasis support/use is
  unverified. [Bluetooth SIG describes the procedure](https://www.bluetooth.com/mesh-remote-provisioning/).
- Proxy advertisements can carry Network ID, Node Identity, Private Network
  Identity, or Private Node Identity. Private proxy identities include random
  data and support periodic BLE address changes. Oasis use of these private
  modes is unverified. [Bluetooth SIG explains private proxies](https://www.bluetooth.com/mesh-private-beacons/).
- Our runtime recognizes Network ID advertisements only. A proxy advertising
  another identity type can therefore escape network-based discovery even if
  the mesh destination has not changed. A name/address fallback can conceal
  this gap. We need captures before choosing which additional modes to support.
- A scan on this Mac at 00:12:42–00:13:28 UTC on October 15 found zero matching
  advertisements (Oasis lamp name or mesh proxy service). No GATT connections
  or lamp changes were made. This does not establish whether the lamp was in
  range, whether its radio was advertising, or whether addresses rotate.

## Reproducible capture

The research scanner now captures unnamed proxies, classifies identity types,
records UTC and elapsed timestamps, and saves scan-only results (previously
`--output` was skipped unless GATT inspection ran).

```sh
python research/ble-research/probe.py --all-proxies --seconds 1800 --output /tmp/oasis-discovery.json
```

Run on a machine within range. Prefer the HA/Pi Bluetooth adapter for testing
actual BLE address changes; macOS exposes a local UUID instead. Keep the same
scanner and record whether Oasis is open, closed, or connected. Repeat across
normal app use without resetting/re-pairing lamps. Multiple addresses sharing
one Network ID may simply be different proxies in the same mesh; that alone
does not prove rotation of one physical lamp. Captures contain nearby device
identifiers and should stay local.

For mesh address changes, compare timestamped exports by node UUID, including
element address ranges, and correlate with an authenticated device response or
account `meshUnicast` diagnostics. Do not match solely by display name or reuse
an old address as device identity. The current checkout has no private account
tokens or before/after exports to perform that comparison.

## Setup friction and verified authentication constraint

The current first screen offers two credential-management tasks. Both funnel
users into a desktop Python/browser installation and JSON upload before they
can choose a lamp. Better wording alone cannot remove that dependency.

The intended flow is: connect Oasis account, choose lamps, check connectivity,
finish. File import belongs in an advanced fallback. A connection check proves
mesh proxy access, not that every selected destination lamp is online; the UI
must distinguish those states. Adding lamps should reuse account/network state
and refresh mappings without creating duplicate entities.

A credential-free check against the public Cognito authorization endpoint with
the client ID already in `tools/export_credentials.py` returned:

| Callback | Result |
| --- | --- |
| `rainmaker://com.mixtiles.oasis/success` | HTTP 302 to `/login` |
| `https://my.home-assistant.io/redirect/oauth` | HTTP 302 to `/error?error=redirect_mismatch…` |

No login or token exchange was performed. This confirms that the standard HA
callback is rejected by this client; it does not enumerate every allowed URL.
[Cognito requires preregistered callback URLs](https://docs.aws.amazon.com/cognito/latest/developerguide/user-pool-settings-client-apps.html).

The clean browser-login solution requires a supported client/callback from
Oasis. An email/password API path would need separate validation of the actual
account authentication method, MFA/challenges, and access-token permissions for
the mesh endpoint; it must not be assumed to support Apple/Google accounts.
A packaged desktop bridge could eliminate Python commands and manual files,
but would still be a companion installation, not native HA browser login.
Do not expose a working-looking account-login action before its return path is
implemented and tested.

## Next evidence needed

1. A longer capture near the lamp on the Pi, covering ordinary Oasis app use.
2. Before/after node mappings if mesh address changes are suspected.
3. A successful account login and mesh retrieval with the new email/password
   form described below.

Validation: 67 tests passed, including scan-only persistence, unnamed proxy
capture, identity classification, and prevention of broad-scan GATT connections.
This is not live Home Assistant or lamp control validation.

## Email/password follow-up

The owner confirmed email/password login. Read-only login feasibility checks
used random nonexistent `example.invalid` accounts, never owner credentials:

| Endpoint / flow | Response |
| --- | --- |
| Cognito `USER_PASSWORD_AUTH` on the known OAuth client | `InvalidParameterException`: flow not enabled |
| Cognito `USER_SRP_AUTH` on the same client | `UserNotFoundException` |
| Oasis `/dev/v1/login2`, `user_name` and `password` JSON | HTTP 400, error 101009, incorrect username or password |

The final request format follows Espressif's
[official CLI login implementation](https://github.com/espressif/esp-rainmaker-cli/blob/master/rmaker_lib/user.py).
This confirms that Oasis exposes a credential-validation endpoint; it does not
prove a successful login or access to node groups for this account.

Implemented `cloud.py` and the native HA email/password form. Successful login
is expected to return `accesstoken`, used with the existing `/user/node_group`
endpoint. Only validated meshes are returned to onboarding. Passwords, access
tokens, refresh tokens, and account profiles are not persisted. Network requests
reject redirects, limit response size, use finite timeouts, and are not retried
automatically. Additional login challenges return an explicit unsupported-step
error with the browser exporter as fallback. File import is under Advanced setup.

Validation: 76 tests passed, including new account transport, challenge/error,
secret-retention, conflicting-key, and login-flow tests. Version 0.3.6 was deployed to Home Assistant 2026.10.1; its configuration check
passed and its native login form rendered. The owner successfully signed in
and reached lamp selection with OASIS_965bac. This verifies account login and
mesh retrieval on the owner’s account. Setup then reported no reachable mesh
proxy, so BLE authentication/control through this flow remain unverified. Existing mesh
destination-address migration is still a separate unresolved task.

## Live discovery follow-up (October 14 evening)

Owner confirmed the lamp was powered near the Pi and the phone app closed.
HA diagnostics showed an operational scanner and five free connection slots.
A short active scan was requested through Bluetooth options; its transition
from passive/auto to active/active was observed, and automatic mode was restored
after the test. The same proxy previously unnamed at F0:EF:F0:72:F2:58 was
observed with the name OASIS_965bac and raw Network ID advertisement payload
00702b7a0ed72cf045. The concurrent 45-second Mac scan independently saw the
same name and payload at CoreBluetooth UUID A2A8BDB2-53B4-9354-6954-831BE2E42C5B.

The current advertised Network ID 702b7a0ed72cf045 differs from the previously
authenticated 3750844603aa1217 in ble-research/evidence.json. Advertisement data
is not authenticated. This is evidence of a changed advertised network identity,
not proof of periodic BLE address or mesh unicast rotation. Whether current
cloud credentials match the live advertisement still needs verification.
No lamp commands, GATT connections, resets, or mesh changes were made in this test.

## Pi GATT cache diagnosis and targeted recovery

The next setup attempt found a nearby mesh proxy but failed before beacon
authentication. HA logged an incomplete GATT table: GAP/GATT and the Espressif
provisioning service were present; mesh proxy characteristics 2ADD and 2ADE
were absent. A single read-only Mac connection to the same named lamp found
both mesh characteristics plus the custom information service.

HA diagnostics confirmed the Pi device was disconnected, unpaired and unbonded.
After rechecking those three properties immediately before acting, a single
BlueZ Adapter1.RemoveDevice was issued for F0:EF:F0:72:F2:58 through the existing
Terminal & SSH add-on. This was a targeted manual cache recovery, not automatic
retry logic. No lamp reset, pairing, mesh configuration or sequence-file changes
were performed. Home Assistant rediscovered the device. A read-only BlueZ
connection then reached ServicesResolved=true and exposed service 1828 with
characteristics 2ADD and 2ADE. The diagnostic connection was disconnected.

This strongly supports stale/incomplete Pi GATT cache as the immediate cause.
Successful onboarding authentication and repeated light control still require
a new setup attempt; GATT service recovery alone does not establish either.

## Live stability investigation (October 20)

With HA 2026.10.1 and the Pi's built-in adapter, the owner reported idle
unavailability and inability to reconnect. Before a lamp power cycle, HA's
scanner was receiving other devices but had no Oasis proxy. After the owner
power-cycled the lamp, the proxy returned with RSSI about -45 dBm, while the
light entity remained unavailable. Reloading only Oasis changed the entity to
unknown (available, with no confirmed lighting state).

One HA turn-on attempt failed with both proxy characteristics absent. Logs
confirmed that the adapter still invoked cache removal and a second connection
after the transport raised IncompleteProxyDiscovery. The installed light.py
matched the repository HEAD before this thread's changes.

An independent read-only Mac inspection found both 2ADD and 2ADE and read
firmware 2.32.1 / ambient_2_0. A subsequent direct BlueZ diagnostic connection
on the Pi reached ServicesResolved=true and exposed both characteristics.
It was disconnected explicitly. No additional manual RemoveDevice, pairing,
provisioning, reset, or sequence-state changes were needed in this sequence.
The next HA turn-on call completed successfully and the entity reported on.
This verifies successful command transmission, not physical light readback.
The exact reason that the GATT table recovered is not established.

Changes prepared from these observations remove the adapter's automatic cache
recovery and reconcile availability every 30 seconds from HA's existing live
Bluetooth discovery cache. The latter opens no connection and sends no mesh
traffic. Regression tests cover missed-callback reconciliation, cleanup,
failed-command state preservation, cancellation, and no automatic replay.

The patched light.py was deployed directly to the owner's HA installation after
verifying the original SHA-256 matched repository HEAD. The original file was
preserved as light.py.before-stability-20261020. The deployed file's SHA-256 is
c28e92622796fbbd27baced0708d941542ef880b29c7f250791731fa18c47f61.
`ha core check` passed, and HA was restarted once. Bluetooth and Oasis both
loaded without reported errors; a post-restart turn-on call succeeded. Local
validation passed all 88 protocol/adapter tests. This is a local hotfix, not a
published HACS release; a future HACS update can replace it.

After restart, a second explicit turn-on command about three minutes after the
first also completed successfully. Eight availability samples over two minutes
all reported on, with no Oasis/Bluetooth errors in HA's system log. Adaptive
Lighting remained enabled; its configuration includes the Oasis light with a
90-second interval, so absence of user actions does not imply absence of
background commands. No automation settings were changed. This short
observation does not establish long-term reliability or physical readback.
