"""Extract only the mesh matching the live beacon, without printing any keys."""
import json
import os
from pathlib import Path

from mesh_crypto import authenticate_beacon, k3
from mesh_protocol import ProxyReassembler

root = Path(__file__).resolve().parent
groups = json.loads((root / "private/node-groups.json").read_text())
observation = json.loads((root / "proxy-observation.json").read_text())
parser = ProxyReassembler()
beacons = []
for record in observation:
    if record["event"] == "proxy_notification":
        result = parser.feed(bytes.fromhex(record["hex"]))
        if result and result[0] == 1 and result[1][0] == 1:
            beacons.append(result[1])
if not beacons:
    raise SystemExit("No observed beacon to authenticate")
matches = []
for group in groups.get("groups", []):
    config = group.get("custom_data", {}).get("ble_mesh_config", {})
    raw = config.get("mesh_data")
    if not raw:
        continue
    mesh = json.loads(raw) if isinstance(raw, str) else raw
    for net_key in mesh.get("netKeys", []):
        key = bytes.fromhex(net_key["key"])
        if any(authenticate_beacon(key, beacon) for beacon in beacons):
            matches.append((mesh, config, net_key["index"], k3(key).hex()))
if len(matches) != 1:
    raise SystemExit(f"Expected one authenticated mesh, got {len(matches)}")
mesh, config, index, network_id = matches[0]
target = root / "private/mesh-export.json"
with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as output:
    json.dump(mesh, output)
print(json.dumps({"beacon_authenticated": True, "network_id": network_id,
                  "network_key_index": index, "mesh_fields": list(mesh),
                  "app_key_indices": [{"index": k["index"], "boundNetKey": k.get("boundNetKey")}
                                      for k in mesh.get("appKeys", [])],
                  "nodes": [{"name": n.get("name"), "unicastAddress": n.get("unicastAddress"),
                             "elements": [{"index": e.get("index"), "models": e.get("models")}
                                          for e in n.get("elements", [])]}
                            for n in mesh.get("nodes", [])],
                  "provisioners": [{"allocatedUnicastRange": p.get("allocatedUnicastRange")}
                                   for p in mesh.get("provisioners", [])]}))
