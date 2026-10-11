# Native BLE command and credential trace — Oasis 2.4.0 (222)

Static analysis of the previously acquired `com.mixtiles.oasis` APK only. No APK execution, hardware interaction, account access, or cloud requests. The original artifact hash/provenance is in `REPORT.md`. `trace_native.py` parses the three DEX files with Androguard and writes disassembly to `analysis/native/`. Offsets below are hexadecimal **byte offsets within each method**, not file offsets. Register counts and input-word counts are retained to make parameter tracing reviewable. Obfuscated class names are preserved.

## Command path established by instructions

| Flutter method | Native implementation | Destination resolution |
|---|---|---|
| `fnBleSendDeviceCommand` | `al/a.onMethodCall` → `vk/e.p` | Exact `target == node.getNodeName()`; first element containing model `48611338 = 0x02E5C00A`; uses that element's address |
| `fnBleSendRoomCommand` | `al/a.onMethodCall` → `vk/e.q` | Exact group-name lookup through `androidx/room/t.F(target)`; uses `Group.getAddress()` |
| `fnBleSendAllDevicesCommand` | `al/a.onMethodCall` → `vk/e.o` | `0xFFFF` |

All method strings have prefix `com.mixtiles.oasis.platform.`. Each accepts JSON `messageId` integer, `payload` integer array, and optional `acknowledged` (default false); device/room also require string `target`. Room optionally accepts integer `ttl`. Every payload integer is narrowed with `int-to-byte` and copied in order; there is no native bounds check to restrict inputs to 0–255. All three take the **first** network AppKey (`bn/p.L`, verified to return list index 0 or null). A missing key returns an error.

Evidence: [bridge](analysis/native/al_a.txt), `onMethodCall` offsets `017e–0214` (all), `0240–02e4` (device), `0936–0a0e` (room); [manager](analysis/native/vk_e.txt), `o`, `p`, `q`; [group lookup](analysis/native/androidx_room_t.txt), `F`; [first-or-null](analysis/native/bn_p.txt), `L`.

## Exact vendor envelope and packing

`vk/e.c(AppKey, messageId, payload, acknowledged, ttl)` selects acknowledged or unacknowledged vendor messages. The former directly calls the Nordic constructor; the latter calls `vk/o.<init>`.

```text
vk/e.c, ack branch:
000008 ushr-int/lit8 v7, v7, 16
00000c and-int/lit8  v4, v7, 63
000010 const        v2, 49162       # model = 0xC00A
000016 const/16     v3, 741         # company = 0x02E5
00001e invoke-direct/range v0...v5 VendorModelMessageAcked.<init>(AppKey,I,I,I,[B)

vk/o.<init>, unack branch: same shift/mask and constants;
optional ttl is assigned to MeshMessage.messageTtl at 000022.
```

The Nordic constructors establish parameter order by assigning these arguments to `mModelIdentifier`, `mCompanyIdentifier`, `mOpCode`, and `mParameters`. `MeshParserUtils.createVendorOpCode` then ORs the opcode with `192` and emits the company ID least-significant byte first. `AccessLayer.createCustomAccessMessage` appends the caller's parameter bytes after these three opcode bytes.

Reconstructed access payload (before mesh encryption/framing):

```text
op = (uint32(messageId) >> 16) & 0x3f
access = bytes([0xc0 | op, 0xe5, 0x02]) + bytes(x & 0xff for x in payload)
```

The low 16 bits of `messageId` are discarded by these generic native command wrappers. Neither model ID nor the full messageId is appended to `payload`. No native transaction ID, brightness conversion, or color-temperature packing occurs here. Optional room TTL is applied **only in the unacknowledged branch**; the acknowledged branch ignores that argument. This is observed implementation behavior, not a recommendation.

Evidence: [vk/e.c](analysis/native/vk_e.txt), [vk/o](analysis/native/vk_o.txt), [acked constructor](analysis/native/no_nordicsemi_android_mesh_transport_VendorModelMessageAcked.txt), [unacked constructor](analysis/native/no_nordicsemi_android_mesh_transport_VendorModelMessageUnacked.txt), [opcode assembly](analysis/native/no_nordicsemi_android_mesh_utils_MeshParserUtils.txt) `createVendorOpCode 000000–00002e`, [access assembly](analysis/native/no_nordicsemi_android_mesh_transport_AccessLayer.txt) `createCustomAccessMessage 000000–000078`.

**Not yet established:** the Dart values selecting on/off, brightness, temperature, or scenes, and the semantic layout of their byte arrays. No lamp command semantics are inferred from strings. The formula above is not a standalone GATT-write command.

## Mesh transport and meaning of success

`createMeshPdu` routes through the Nordic stack. `VendorModelMessageUnackedState.createAccessMessage` passes the selected AppKey, opcode, company ID, parameters, source/destination, and TTL into `MeshTransport.createVendorMeshMessage`. `UpperTransportLayer.encryptUpperTransportPDU` calls `SecureUtils.encryptCCM`. `nh/u.onMeshPduCreated` passes the resulting PDU to `vk/w.m`, then to open proxies through `vk/n.c`. That code explicitly resolves service `0x1828` and Data In `0x2ADD`; `vk/n.d` writes the characteristic (legacy API sets write type 1). Notifications are enabled on `0x2ADE` by `vk/w.a`.

The command callbacks report success immediately after `createMeshPdu` returns (`o:000096`, `p:0001ca`, `q:000210`). They do **not** establish lamp acknowledgement or a changed light state. `vk/w.m` can merely log that no proxy is open.

Evidence: [transport state](analysis/native/no_nordicsemi_android_mesh_transport_VendorModelMessageUnackedState.txt), [CCM path](analysis/native/no_nordicsemi_android_mesh_transport_UpperTransportLayer.txt), [PDU callback](analysis/native/nh_u.txt), [proxy manager](analysis/native/vk_w.txt), [GATT writer](analysis/native/vk_n.txt), [UUID constants](analysis/native/vk_b.txt).

## Key acquisition, export/import, and state

The native initialization calls `MeshManagerApi.loadMeshNetwork` (`vk/e.j:0001fe`). The database is named `mesh_network_database.db` (`MeshNetworkDb.getDatabase`). A failed load calls `vk/e.a`, which creates a network only if absent. `MeshManagerApi.generateNetKeys` creates one NetKey at index 0; `generateAppKeys` creates three AppKeys at indices 0–2, each via `SecureUtils.generateRandomNumber`. **Generating a new network's keys will not recover this lamp's existing credentials.** No per-user keys were obtained from the static APK.

Export: `al/a.onMethodCall:00081c` calls `MeshManagerApi.exportMeshNetwork()` and returns the resulting string in `meshData`. The library calls `ImportExportUtils.export(network,false)`, sets `partial=false`, and serializes with Gson. Its adapters explicitly serialize `netKeys`, `appKeys`, `nodes`, `provisioners`, groups, and scenes. `NetKeyDeserializer.serialize` and `AppKeyDeserializer.serialize` put `getKey()` bytes into hex string `key`; `NodeDeserializer.serialize` emits hex `deviceKey`. This export is a concrete owner-state credential source, not merely a list of device names.

Import: JSON string `meshData` → `vk/e.i` → `MeshManagerApi.importMeshNetworkJson` → `ImportExportUtils.importNetwork`/Gson. Import disconnects the current connection via `vk/w.b`, then waits on the stored callback `vk/e.w`; `nh/u.onNetworkImported` or `onNetworkImportFailed` resolves it. The app restores its locally saved provisioner UUID (`ble_mesh_provisioner` preferences), or adds a local provisioner with available address ranges, then resumes connection handling.

For an existing mesh UUID, library import copies matching nodes' sequence numbers from local DB, calls `loadSequenceNumbers`, and retains the prior local `ivIndex` (`importMeshNetworkJson:0000be–0000dc`). The exported mesh serializer has **no top-level live IV-index or sequence-number field**; an `ivIndex` inside network-exclusion entries is not that state. Keys from cloud export alone do not settle sender address/sequence state. The main agent's separately observed beacon may establish the current IV index; it does not reveal either secret key.

Evidence: [manager initialization/import](analysis/native/vk_e.txt), [library key generation/import](analysis/native/no_nordicsemi_android_mesh_MeshManagerApi.txt), [database](analysis/native/no_nordicsemi_android_mesh_MeshNetworkDb.txt), [export/import utility](analysis/native/no_nordicsemi_android_mesh_ImportExportUtils.txt), [mesh JSON adapter](analysis/native/no_nordicsemi_android_mesh_MeshNetworkDeserializer.txt), [NetKey adapter](analysis/native/no_nordicsemi_android_mesh_NetKeyDeserializer.txt), [AppKey adapter](analysis/native/no_nordicsemi_android_mesh_AppKeyDeserializer.txt), [node adapter](analysis/native/no_nordicsemi_android_mesh_transport_NodeDeserializer.txt), [import callbacks](analysis/native/nh_u.txt).

Cloud `ble_mesh_config` endpoint acquisition is assigned to the main agent; its exact response wrapper is not proven by this native trace.

## Other local paths and supplied UUIDs

`SendDataArguments.Companion.fromJson` parses `deviceName` (default empty string) and a JSON-object `payload` (default empty object). It belongs to `fnSendDataToLocal`, not the three BLE mesh handlers. The native call chain is `al/a → zk/a.c`, producing UTF-8 JSON inside `EspLocalCtrl.PropertyValue → CmdSetPropertyValues → LocalCtrlMessage`. It sets a PoP from a node-keyed map and Security1, then calls `wk/c.b`; `wk/c.a` builds an HTTP transport and `wk/c.b` targets `esp_local_ctrl/control`. Detailed Wi-Fi discovery/cloud work remains with the main agent. Evidence: [argument parser](analysis/native/com_mixtiles_oasis_platform_models_SendDataArguments$Companion.txt), [local send](analysis/native/zk_a.txt), [local transport](analysis/native/wk_c.txt).

The supplied provisioning service `021a9004-0382-4aea-bff4-6b3f1c5adfb4` occurs in `cl/l.<clinit>` and `vk/b.<clinit>`. `cl/b.a` creates an Espressif BLE device initially configured for Security1. The six `021aff4f–021aff54` characteristic UUID assignments are **not hardcoded in the inspected DEX**: `BLETransport.readNextDescriptor` reads descriptors matching `2901`; `BLETransport$1.onDescriptorRead` UTF-8 decodes descriptor values and maps endpoint-name → characteristic UUID. Therefore neither the short UUID sequence nor empty descriptors proves a particular control endpoint.

`ESPDevice.initSession` reads version JSON `prov.sec_ver`, negotiates Security0/1/2, and clears PoP only when capabilities contain `no_pop`. `Session.init` sends the security handshake to `prov-session`; `Session.sendDataToDevice` calls the chosen security implementation's `encrypt` before transport. An app-specific custom endpoint visible in `cl/e.invoke` is `cloud_user_assoc`, carrying a Rainmaker user-association protobuf, not a lamp-power command. Read/write characteristic flags do not prove an unauthenticated light-control API.

Evidence: [service constants](analysis/native/cl_l.txt), [BLE setup](analysis/native/cl_b.txt), [descriptor discovery](analysis/native/com_espressif_provisioning_transport_BLETransport.txt), [descriptor mapping](analysis/native/com_espressif_provisioning_transport_BLETransport$1.txt), [session selection](analysis/native/com_espressif_provisioning_ESPDevice.txt), [session encryption](analysis/native/com_espressif_provisioning_Session.txt), [custom association endpoint](analysis/native/cl_e.txt).

## Remaining proof required for actual lamp control

Obtain the owner's existing NetKey/AppKey and mesh node/group mapping; correlate network identity; establish correct sender address/sequence and current IV state; recover Dart message IDs and payload builders for a specific non-destructive light action. Static native analysis has established the transport, key source, routing, and wire envelope, but has not verified a successful lamp control operation. Hardware observations supplied by the main agent were not independently reproduced here.
