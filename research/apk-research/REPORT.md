# Oasis Android acquisition and static inspection

Acquired 2026-10-11 at approximately 16:17 UTC. No app installation or execution was performed. All task writes are inside this directory; no HACS repository edits.

## Provenance

- Mirror landing page: https://apkpure.net/oasis/com.mixtiles.oasis/download/2.4.0
- Download URL observed in browser DOM: https://d.apkpure.net/b/XAPK/com.mixtiles.oasis?versionCode=222&nc=arm64-v8a&sv=24
- HTTP redirect served the archive from `data.winudf.com`; exact redirect and response headers are in `download-headers.txt`.
- Local artifact: `oasis-2.4.0-arm64.xapk` (58,118,211 bytes).
- SHA-256: `7c5152e57a1de0fbc97a4d56edbde8803500beeb8a63869021766b32d9872691`. Matches the mirror's displayed archive hash.
- Base APK: `extracted/com.mixtiles.oasis.apk`, SHA-256 `76ced0cc67d3b358a7c001dcf90354c7431145a799737f90e5acde0cb4f7b8b8`.
- Initial sandboxed curl failed DNS resolution. The preview browser loaded the landing page after its initial Cloudflare interstitial. Authorized network-enabled curl successfully downloaded the direct URL. Further mirrors were unnecessary after acquisition.

## Identity derived from the APK

The binary Android manifest, parsed with Androguard 4.1.4, identifies `com.mixtiles.oasis`, version `2.4.0`, version code `222`, minimum SDK `24`, target SDK `36`, and launch activity `com.mixtiles.oasis.MainActivity`. See `analysis/AndroidManifest.xml` and `analysis/apk-metadata.json`. This is independently read from the downloaded APK, not merely copied from XAPK metadata.

APK v2 and v3 signature blocks are present; v1 is absent in the base APK. Extracted signing certificate: `analysis/signer-0.der`.

- Certificate SHA-1: `562e33d7a844929a9a1adec28ec081515e3fe739` (matches the mirror's advertised signature).
- Certificate SHA-256: `1df9913c305e391fda444939559ae1e307827514296550f19c668bef19b6248e`.
- Subject and issuer: CN=Android, OU=Android, O=Google Inc., L=Mountain View, ST=California, C=US.

These are certificate extraction and signature-presence results, not full cryptographic APK signature verification. Android SDK tools/apksigner and a functioning Java runtime were unavailable. A generic certificate subject does not prove publisher identity. No independent publisher-controlled signing fingerprint or independently obtained Google Play artifact was available for comparison. APKPure's developer verification and safety claims remain mirror assertions; hash agreement establishes consistency with that mirror, not independently authenticated publisher identity.

## Archive structure and framework

The XAPK contains 22 entries: base APK, 19 configuration APKs (ARM64 native libraries, xxhdpi resources, and 17 language splits), `manifest.json`, and `icon.png`. Full size/name inventories for the XAPK and every APK are under `analysis/*.inventory.txt`; all APK SHA-256 values are in `analysis/sha256.json`.

The base includes `classes.dex`, `classes2.dex`, `classes3.dex`, Android resources, and `assets/flutter_assets/`. The ARM64 split includes `libflutter.so`, `libapp.so`, `libdartjni.so`, `librive_native.so`, Sentry libraries, and image/barcode support libraries. This identifies Flutter with compiled Dart AOT application code plus native Android integration. `analysis/libapp.so` is an extracted, stripped ARM64 ELF file retained for static analysis. The three DEX files are also retained under `analysis/`.

Actual DEX classes confirm:

- Nordic Android Mesh: `no.nordicsemi.android.mesh.MeshManagerApi`, transport/provisioning classes, `VendorModelMessageAcked`, `VendorModelMessageUnacked`, and standard lighting/scene models.
- Espressif provisioning: `com.espressif.provisioning.ESPProvisionManager`, `ESPDevice`, `transport.BLETransport`, and Security0/1/2 implementations.
- Oasis native bridge models under `com.mixtiles.oasis.platform.models`, including `ProvisionArguments` and `SendDataArguments`.

Dart strings reference Rainmaker provisioning, `ble_mesh_config`, `BackgroundBleProvisioningService`, mesh cloud synchronization, and native BLE mesh initialization. These are static evidence of code paths, not proof of which path the user's particular lamp uses. The Flutter `mesh_gradient` shader assets are visual effects and must not be confused with Bluetooth mesh evidence.

## Concrete next analysis leads

1. Trace Flutter/native bridge strings `com.mixtiles.oasis.platform.fnBleSendRoomCommand`, `fnBleChangeRoom`, `fnBleInitialize`, `fnBleProvision`, `fnBleExportMeshData`, and `fnBleImportMeshData` into DEX callers and implementations. Resolve command parameters, destination addresses, model IDs, and opcodes.
2. Inspect app-specific calls into Nordic `MeshManagerApi` and vendor-message constructors to distinguish standard lighting models from custom messages. Library presence alone does not establish the lamp's protocol/model selection.
3. Follow `ble_mesh_config`, `_downloadMeshFromCloud`, and mesh export/import references in the Dart AOT code to determine mesh schema and how the owner's network/app keys are stored and synchronized. No user keys were accessed in this task.
4. Trace Espressif BLE transport and Rainmaker provisioning paths to establish whether Wi-Fi/Rainmaker control is separate from the Bluetooth mesh path.
5. Before relying on publisher authenticity, obtain an independent publisher-controlled certificate fingerprint or trusted Play-delivered APK and perform full APK signature verification.

Search indexes: `analysis/dex-classes.txt`, `analysis/dex-relevant-strings.txt`, `analysis/dart-relevant-strings.txt`, and `analysis/flutter-assets.txt`. Reproducible extraction script: `inspect_apk.py`; task-local parser environment: `tools-venv/`. These tools parse archive/code data; they do not launch the app.
