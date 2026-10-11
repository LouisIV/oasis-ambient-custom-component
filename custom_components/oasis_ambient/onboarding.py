"""Credential import and conservative local sender reservations (no HA APIs)."""
import hashlib
import json
import os
from pathlib import Path
import secrets

MAX_EXPORT_BYTES = 5 * 1024 * 1024


def parse_export(raw):
    if len(raw) > MAX_EXPORT_BYTES:
        raise ValueError('Export is too large')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('Expected an Oasis credential export')
    meshes = value.get('meshes') if value.get('oasis_export') == 1 else [value]
    if not isinstance(meshes, list) or not meshes:
        raise ValueError('No mesh networks found')
    for mesh in meshes:
        if not isinstance(mesh, dict):
            raise ValueError('Invalid mesh network')
        if not isinstance(mesh.get('meshUUID'), str):
            raise ValueError('Missing mesh identity')
        for kind in ('netKeys', 'appKeys'):
            keys = mesh.get(kind)
            if not isinstance(keys, list) or not keys:
                raise ValueError('Missing mesh keys')
            for key in keys:
                if len(bytes.fromhex(key['key'])) != 16:
                    raise ValueError('Invalid mesh key')
        if not isinstance(mesh.get('nodes'), list):
            raise ValueError('Missing nodes')
        for node in mesh['nodes']:
            if not isinstance(node, dict):
                raise ValueError('Invalid mesh node')
            if not 1 <= int(node['unicastAddress'], 16) <= 0x7fff:
                raise ValueError('Invalid node address')
    return meshes


def mesh_identity(mesh):
    net = next(k for k in mesh['netKeys'] if k['index'] == 0)
    return mesh['meshUUID'] + ':' + hashlib.sha256(bytes.fromhex(net['key'])).hexdigest()


def lamp_choices(meshes):
    choices = {}
    for index, mesh in enumerate(meshes):
        for node in mesh['nodes']:
            elements = node.get('elements', [])
            models = elements[0].get('models', []) if elements else []
            if any(m.get('modelId', '').upper() == '02E5C00A' and 0 in m.get('bind', []) for m in models):
                name = node.get('name', '')
                if name:
                    choices[f"{mesh_identity(mesh)}:{int(node['unicastAddress'], 16):04x}"] = (mesh, node)
    return choices


def reserve_sender(mesh, root):
    """Reserve a random unused address atomically. Tombstones are never removed.

    Existing exported allocations and this HA installation are excluded. An
    independent controller unknown to both cannot be detected; never clone an
    active installation or restore stale counters.
    """
    used = {0x7fff}  # Earlier Mac research controller; leave it retired here.
    for node in mesh['nodes']:
        start = int(node['unicastAddress'], 16)
        used.update(range(start, start + max(1, len(node.get('elements', [])))))
    for provisioner in mesh.get('provisioners', []):
        for span in provisioner.get('allocatedUnicastRange', []):
            low, high = int(span['lowAddress'], 16), int(span['highAddress'], 16)
            if not 1 <= low <= high <= 0x7fff:
                raise ValueError('Invalid provisioner allocation')
            used.update(range(low, high + 1))
    net = next(k for k in mesh['netKeys'] if k['index'] == 0)
    identity = hashlib.sha256((mesh['meshUUID'] + ':' + net['key'].lower()).encode()).hexdigest()[:24]
    directory = Path(root) / 'senders' / identity
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Randomize so two independent installations do not always choose 0x7ffe.
    available = list(set(range(0x1000, 0x7fff)) - used)
    secrets.SystemRandom().shuffle(available)
    for source in available:
        reservation = directory / f'{source:04x}'
        try:
            reservation.mkdir(mode=0o700)
        except FileExistsError:
            continue
        return source, reservation
    raise ValueError('No free local sender address')


def save_mesh(mesh, target):
    """Exclusive private write; never overwrite another entry's credentials."""
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream:
        json.dump(mesh, stream)
