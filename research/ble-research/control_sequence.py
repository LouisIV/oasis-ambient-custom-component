"""Explicit single-lamp visual test using APK-derived Oasis vendor commands."""
import asyncio
import argparse
import hashlib
import json

from bleak import BleakClient, BleakScanner
from cryptography.exceptions import InvalidTag
from mesh_crypto import (NetworkMessage, authenticate_beacon, decrypt_access,
                         decrypt_network, encrypt_access, encrypt_network)
from mesh_protocol import ProxyReassembler, SecureNetworkBeacon, fragment_proxy
from sequence_store import SequenceStore
from query_lamp import ROOT, PROXY_IN, PROXY_OUT, SOURCE
from oasis_commands import power, brightness, brightness_temperature, rgb, color_mode


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--green', action='store_true', help='Send only pure green RGB')
    args = parser.parse_args()
    mesh = json.loads((ROOT / 'private/mesh-export.json').read_text())
    lamp = next(n for n in mesh['nodes'] if n.get('name') == 'OASIS_965bac')
    dst = int(lamp['unicastAddress'], 16)
    net = bytes.fromhex(next(k['key'] for k in mesh['netKeys'] if k['index'] == 0))
    app = bytes.fromhex(next(k['key'] for k in mesh['appKeys'] if k['index'] == 0))
    ready = asyncio.Event()
    state = {'iv': None}
    assembler = ProxyReassembler()
    records = []

    def record(**event):
        records.append(event)
        print(json.dumps(event), flush=True)

    def notification(_, value):
        try:
            result = assembler.feed(value)
            if result is None:
                return
            kind, data = result
            if kind == 1 and authenticate_beacon(net, data):
                beacon = SecureNetworkBeacon.parse(data)
                if beacon.key_refresh or beacon.iv_update:
                    raise ValueError('Unsupported key/IV transition')
                state['iv'] = beacon.iv_index
                ready.set()
                record(event='authenticated_beacon', iv_index=beacon.iv_index)
            elif kind == 0 and state['iv'] is not None:
                msg = decrypt_network(net, state['iv'], data)
                if msg.source == dst:
                    access = decrypt_access(app, state['iv'], msg)
                    record(event='authenticated_vendor_response', access=access.hex(),
                           sequence=msg.sequence, destination=f'{msg.destination:04x}')
        except (ValueError, InvalidTag) as error:
            record(event='ignored_packet', reason=type(error).__name__)

    device = await BleakScanner.find_device_by_filter(
        lambda d, a: (a.local_name or d.name) == 'OASIS_965bac', timeout=20)
    if device is None:
        raise RuntimeError('Lamp not found; disconnect phone BLE apps')
    try:
        async with BleakClient(device, timeout=20) as client:
            await client.start_notify(PROXY_OUT, notification)
            await asyncio.wait_for(ready.wait(), 15)
            iv = state['iv']
            identity = mesh['meshUUID'] + ':' + hashlib.sha256(net).hexdigest()
            seqs = SequenceStore(ROOT / 'private/sender.db', identity, SOURCE, iv)
            try:
                async def send(label, access):
                    if state['iv'] != iv:
                        raise RuntimeError('IV changed during test')
                    seq = seqs.allocate()
                    lower = encrypt_access(app, iv, seq, SOURCE, dst, access)
                    pdu = encrypt_network(net, iv, NetworkMessage(0, 5, seq, SOURCE, dst, lower))
                    for chunk in fragment_proxy(0, pdu):
                        await client.write_gatt_char(PROXY_IN, chunk, response=False)
                    record(event='command_sent_not_confirmed', command=label, sequence=seq,
                           access=access.hex())

                if args.green:
                    await send('color_mode_rgb', color_mode(True))
                    await asyncio.sleep(0.3)
                    await send('rgb_green', rgb(0, 255, 0))
                else:
                    await send('off', power(False))
                    await asyncio.sleep(4)
                    await send('brightness_1_percent', brightness(1))
                    await send('on', power(True))
                    await asyncio.sleep(4)
                    await send('brightness_100_percent_6500_kelvin', brightness_temperature(100, 6500))
                await asyncio.sleep(5)
            finally:
                seqs.close()
            await client.stop_notify(PROXY_OUT)
    finally:
        output = 'green-mode-observation.json' if args.green else 'control-sequence-observation.json'
        (ROOT / output).write_text(json.dumps(records, indent=2) + '\n')


if __name__ == '__main__':
    asyncio.run(main())
