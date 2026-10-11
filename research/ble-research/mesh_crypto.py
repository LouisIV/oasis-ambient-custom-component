"""Bluetooth Mesh key derivation and secure-beacon authentication.

Algorithms: Bluetooth Mesh Protocol 1.1 section 3.9; test vectors in section 8.
No key generation, account access, BLE writes, or sequence allocation here.
"""
import hmac
from dataclasses import dataclass

from cryptography.hazmat.primitives.cmac import CMAC
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESCCM


def cmac(key: bytes, message: bytes) -> bytes:
    if len(key) != 16:
        raise ValueError("Mesh AES keys must be 16 bytes")
    instance = CMAC(algorithms.AES(key))
    instance.update(message)
    return instance.finalize()


def s1(message: bytes) -> bytes:
    return cmac(bytes(16), message)


def k1(material: bytes, salt: bytes, info: bytes) -> bytes:
    return cmac(cmac(salt, material), info)


def k2(net_key: bytes, p: bytes = b"\x00") -> tuple[int, bytes, bytes]:
    if len(net_key) != 16:
        raise ValueError("NetKey must be 16 bytes")
    t = cmac(s1(b"smk2"), net_key)
    t1 = cmac(t, p + b"\x01")
    t2 = cmac(t, t1 + p + b"\x02")
    t3 = cmac(t, t2 + p + b"\x03")
    return t1[-1] & 0x7f, t2, t3


def k3(net_key: bytes) -> bytes:
    if len(net_key) != 16:
        raise ValueError("NetKey must be 16 bytes")
    t = cmac(s1(b"smk3"), net_key)
    return cmac(t, b"id64\x01")[-8:]


def k4(app_key: bytes) -> int:
    if len(app_key) != 16:
        raise ValueError("AppKey must be 16 bytes")
    t = cmac(s1(b"smk4"), app_key)
    return cmac(t, b"id6\x01")[-1] & 0x3f


def beacon_key(net_key: bytes) -> bytes:
    if len(net_key) != 16:
        raise ValueError("NetKey must be 16 bytes")
    return k1(net_key, s1(b"nkbk"), b"id128\x01")


def authenticate_beacon(net_key: bytes, payload: bytes) -> bool:
    """Authenticate a complete 22-byte beacon, never a proxy SAR fragment."""
    if len(payload) != 22 or payload[0] != 1 or payload[1] & ~3:
        return False
    if not hmac.compare_digest(k3(net_key), payload[2:10]):
        return False
    return hmac.compare_digest(cmac(beacon_key(net_key), payload[1:14])[:8], payload[14:])


@dataclass(frozen=True)
class NetworkMessage:
    ctl: int
    ttl: int
    sequence: int
    source: int
    destination: int
    lower_transport: bytes


def _validate(message: NetworkMessage, iv_index: int):
    if message.ctl not in (0, 1) or not 0 <= message.ttl <= 127:
        raise ValueError("Invalid CTL or TTL")
    if not 0 <= message.sequence <= 0xffffff or not 0 <= iv_index <= 0xffffffff:
        raise ValueError("Sequence or IV index out of range")
    if not 1 <= message.source <= 0x7fff or not 1 <= message.destination <= 0xffff:
        raise ValueError("Invalid source or destination")
    maximum = 12 if message.ctl else 16
    if not 1 <= len(message.lower_transport) <= maximum:
        raise ValueError("Lower transport PDU length out of range")


def _privacy_mask(key: bytes, iv_index: int, encrypted: bytes) -> bytes:
    block = bytes(5) + iv_index.to_bytes(4, "big") + encrypted[:7]
    cipher = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return (cipher.update(block) + cipher.finalize())[:6]


def encrypt_network(net_key: bytes, iv_index: int, message: NetworkMessage) -> bytes:
    """Managed-flooding Network PDU. Caller must durably allocate a fresh SEQ."""
    _validate(message, iv_index)
    nid, encryption, privacy = k2(net_key)
    header = bytes([(message.ctl << 7) | message.ttl]) + message.sequence.to_bytes(3, "big") + message.source.to_bytes(2, "big")
    nonce = b"\x00" + header + bytes(2) + iv_index.to_bytes(4, "big")
    plaintext = message.destination.to_bytes(2, "big") + message.lower_transport
    encrypted = AESCCM(encryption, tag_length=8 if message.ctl else 4).encrypt(nonce, plaintext, None)
    mask = _privacy_mask(privacy, iv_index, encrypted)
    obfuscated = bytes(a ^ b for a, b in zip(header, mask))
    return bytes([((iv_index & 1) << 7) | nid]) + obfuscated + encrypted


def decrypt_network(net_key: bytes, iv_index: int, pdu: bytes) -> NetworkMessage:
    """Authenticate/decrypt a PDU; caller must separately enforce replay checks."""
    if not 0 <= iv_index <= 0xffffffff or not 14 <= len(pdu) <= 29:
        raise ValueError("Invalid IV index or Network PDU length")
    nid, encryption, privacy = k2(net_key)
    if pdu[0] != ((iv_index & 1) << 7) | nid:
        raise ValueError("Network identity or IV parity mismatch")
    mask = _privacy_mask(privacy, iv_index, pdu[7:])
    header = bytes(a ^ b for a, b in zip(pdu[1:7], mask))
    ctl = header[0] >> 7
    nonce = b"\x00" + header + bytes(2) + iv_index.to_bytes(4, "big")
    plain = AESCCM(encryption, tag_length=8 if ctl else 4).decrypt(nonce, pdu[7:], None)
    result = NetworkMessage(ctl, header[0] & 127, int.from_bytes(header[1:4], "big"),
                            int.from_bytes(header[4:6], "big"), int.from_bytes(plain[:2], "big"), plain[2:])
    _validate(result, iv_index)
    return result


def _access_nonce(iv_index: int, sequence: int, source: int, destination: int, device_key: bool) -> bytes:
    if not 0 <= sequence <= 0xffffff or not 0 <= iv_index <= 0xffffffff:
        raise ValueError("Sequence or IV index out of range")
    # Virtual addresses need label-UUID AAD and are deliberately not supported.
    if not 1 <= source <= 0x7fff or not (1 <= destination <= 0x7fff or 0xc000 <= destination <= 0xffff):
        raise ValueError("Invalid source or unsupported destination")
    return bytes([2 if device_key else 1, 0]) + sequence.to_bytes(3, "big") + source.to_bytes(2, "big") + destination.to_bytes(2, "big") + iv_index.to_bytes(4, "big")


def encrypt_access(key: bytes, iv_index: int, sequence: int, source: int,
                   destination: int, access: bytes, *, device_key: bool = False) -> bytes:
    """Unsegmented lower-transport access PDU, 32-bit TransMIC."""
    if len(key) != 16 or not 1 <= len(access) <= 11:
        raise ValueError("Expected 16-byte key and 1–11-byte access message")
    nonce = _access_nonce(iv_index, sequence, source, destination, device_key)
    encrypted = AESCCM(key, tag_length=4).encrypt(nonce, access, None)
    return bytes([0 if device_key else 0x40 | k4(key)]) + encrypted


def decrypt_access(key: bytes, iv_index: int, message: NetworkMessage, *, device_key: bool = False) -> bytes:
    """Unsegmented access only; authenticates before returning plaintext."""
    lower = message.lower_transport
    expected = 0 if device_key else 0x40 | k4(key)
    if len(key) != 16 or message.ctl or not 6 <= len(lower) <= 16 or lower[0] != expected:
        raise ValueError("Not a supported unsegmented access message for this key")
    nonce = _access_nonce(iv_index, message.sequence, message.source, message.destination, device_key)
    return AESCCM(key, tag_length=4).decrypt(nonce, lower[1:], None)
