"""Read the lamp's Config Default TTL over authenticated Bluetooth Mesh.

No reset, provisioning, or lamp-state change is performed. This reserves local
sender 0x7fff (outside every allocation in the imported mesh) and persists SEQ.
"""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from bleak import BleakClient, BleakScanner
from cryptography.exceptions import InvalidTag

from mesh_crypto import (NetworkMessage, authenticate_beacon, decrypt_access,
                         decrypt_network, encrypt_access, encrypt_network)
from mesh_protocol import ProxyReassembler, SecureNetworkBeacon, fragment_proxy
from sequence_store import SequenceStore

ROOT = Path(__file__).resolve().parent
PROXY_IN = "00002add-0000-1000-8000-00805f9b34fb"
PROXY_OUT = "00002ade-0000-1000-8000-00805f9b34fb"
SOURCE = 0x7fff


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--initialize-sender", action="store_true")
    args = parser.parse_args()
    mesh = json.loads((ROOT / "private/mesh-export.json").read_text())
    lamp = next(n for n in mesh["nodes"] if n.get("name") == "OASIS_965bac")
    destination = int(lamp["unicastAddress"], 16)
    net_key = bytes.fromhex(next(k["key"] for k in mesh["netKeys"] if k["index"] == 0))
    dev_key = bytes.fromhex(lamp["deviceKey"])
    for node in mesh["nodes"]:
        first = int(node["unicastAddress"], 16)
        if first <= SOURCE < first + max(1, len(node.get("elements", []))):
            raise ValueError("Sender address already belongs to a node")
    for provisioner in mesh["provisioners"]:
        for allocation in provisioner.get("allocatedUnicastRange", []):
            if int(allocation["lowAddress"], 16) <= SOURCE <= int(allocation["highAddress"], 16):
                raise ValueError("Sender address belongs to an existing provisioner's range")
    records = []

    def record(value):
        records.append(value)
        print(json.dumps(value), flush=True)

    device = await BleakScanner.find_device_by_filter(
        lambda d, a: (a.local_name or d.name) == "OASIS_965bac", timeout=20)
    if device is None:
        raise RuntimeError("Lamp not found; disconnect phone BLE apps and retry")
    beacon_ready = asyncio.Event()
    response_ready = asyncio.Event()
    state = {"iv_index": None, "last_sequence": -1}
    assembler = ProxyReassembler()

    def notification(_, value):
        try:
            completed = assembler.feed(value)
            if completed is None:
                return
            kind, payload = completed
            if kind == 1 and authenticate_beacon(net_key, payload):
                beacon = SecureNetworkBeacon.parse(payload)
                if beacon.key_refresh or beacon.iv_update:
                    record({"event": "unsupported_mesh_transition"})
                    return
                state["iv_index"] = beacon.iv_index
                beacon_ready.set()
                record({"event": "authenticated_live_beacon", "iv_index": beacon.iv_index})
            elif kind == 0 and state["iv_index"] is not None:
                message = decrypt_network(net_key, state["iv_index"], payload)
                if message.source != destination or message.destination != SOURCE:
                    return
                if message.sequence <= state["last_sequence"]:
                    return
                access = decrypt_access(dev_key, state["iv_index"], message, device_key=True)
                state["last_sequence"] = message.sequence
                record({"event": "authenticated_config_response", "source": f"{message.source:04x}",
                        "sequence": message.sequence, "access": access.hex()})
                if len(access) == 3 and access[:2] == bytes.fromhex("800e"):
                    record({"event": "default_ttl", "value": access[2]})
                    response_ready.set()
        except (ValueError, InvalidTag) as error:
            record({"event": "ignored_packet", "reason": type(error).__name__})

    try:
        async with BleakClient(device, timeout=20) as client:
            await client.start_notify(PROXY_OUT, notification)
            await asyncio.wait_for(beacon_ready.wait(), 15)
            iv_index = state["iv_index"]
            identity = mesh["meshUUID"] + ":" + hashlib.sha256(net_key).hexdigest()
            sequences = SequenceStore(ROOT / "private/sender.db", identity, SOURCE, iv_index,
                                      initialize=args.initialize_sender)
            try:
                sequence = sequences.allocate()
                lower = encrypt_access(dev_key, iv_index, sequence, SOURCE, destination,
                                       bytes.fromhex("800c"), device_key=True)
                pdu = encrypt_network(net_key, iv_index, NetworkMessage(0, 5, sequence, SOURCE, destination, lower))
                for chunk in fragment_proxy(0, pdu):
                    await client.write_gatt_char(PROXY_IN, chunk, response=False)
                record({"event": "default_ttl_get_sent", "source": f"{SOURCE:04x}",
                        "destination": f"{destination:04x}", "sequence": sequence})
                await asyncio.wait_for(response_ready.wait(), 15)
            finally:
                sequences.close()
            await client.stop_notify(PROXY_OUT)
    finally:
        (ROOT / "ttl-query-observation.json").write_text(json.dumps(records, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
