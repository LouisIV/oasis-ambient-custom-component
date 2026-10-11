"""Non-mutating discovery and GATT inventory of the user's Oasis lamp."""
import argparse
import asyncio
import json
from pathlib import Path

from bleak import BleakClient, BleakScanner
from mesh_protocol import ProxyReassembler, SecureNetworkBeacon

INFO_UUID = "dcfecdab-9876-5431-dcfe-cdab98765431"


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="OASIS_965bac")
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--listen-proxy", type=float, default=0,
                        help="Seconds to receive mesh proxy notifications; sends no mesh commands")
    args = parser.parse_args()
    found = {}
    records = []

    def record(value):
        records.append(value)
        print(json.dumps(value), flush=True)

    def seen(device, advertisement):
        if args.name not in (advertisement.local_name, device.name):
            return
        found[device.address] = device
        record({"event": "advertisement", "address": device.address,
                          "name": advertisement.local_name, "rssi": advertisement.rssi,
                          "services": advertisement.service_uuids,
                          "service_data": {k: v.hex() for k, v in advertisement.service_data.items()}})

    async with BleakScanner(detection_callback=seen):
        await asyncio.sleep(args.seconds)
    record({"event": "scan_complete", "matches": len(found)})
    if not args.inspect:
        return
    if len(found) != 1:
        raise RuntimeError("Expected exactly one matching lamp before connecting")
    async with BleakClient(next(iter(found.values())), timeout=20) as client:
        record({"event": "connected", "mtu": client.mtu_size})
        for service in client.services:
            record({"event": "service", "uuid": service.uuid,
                              "characteristics": [{"uuid": c.uuid, "properties": c.properties}
                                                  for c in service.characteristics]})
            for characteristic in service.characteristics:
                for descriptor in characteristic.descriptors:
                    if descriptor.uuid.lower() == "00002901-0000-1000-8000-00805f9b34fb":
                        value = await client.read_gatt_descriptor(descriptor.handle)
                        record({"event": "description", "characteristic": characteristic.uuid,
                                "text": value.decode("utf-8", errors="replace")})
        # Only read the already identified, read-only firmware information endpoint.
        data = await client.read_gatt_char(INFO_UUID)
        record({"event": "device_info", "hex": data.hex(),
                "text": data.decode("utf-8", errors="replace")})
        if args.listen_proxy:
            proxy_out = "00002ade-0000-1000-8000-00805f9b34fb"
            reassembler = ProxyReassembler()
            def notification(_, value):
                record({"event": "proxy_notification", "hex": value.hex()})
                try:
                    message = reassembler.feed(value)
                    if message and message[0] == 1 and message[1][0] == 1:
                        beacon = SecureNetworkBeacon.parse(message[1])
                        record({"event": "secure_network_beacon", "authenticated": False,
                                "network_id": beacon.network_id.hex(), "iv_index": beacon.iv_index,
                                "key_refresh": beacon.key_refresh, "iv_update": beacon.iv_update})
                except ValueError as error:
                    record({"event": "proxy_parse_error", "error": str(error)})
            await client.start_notify(proxy_out, notification)
            await asyncio.sleep(args.listen_proxy)
            await client.stop_notify(proxy_out)
    if args.output:
        args.output.write_text(json.dumps(records, indent=2) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
