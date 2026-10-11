"""Bluetooth Mesh Proxy framing, independent of BLE backend and lamp commands.

Beacon parsing is structural only. Do not trust IV/key-refresh state until the
beacon authentication value has been verified using the correct network key.
"""
from dataclasses import dataclass
from time import monotonic


def fragment_proxy(message_type: int, payload: bytes, value_size: int = 20) -> list[bytes]:
    """Split a proxy message into characteristic values (ATT MTU minus 3)."""
    if message_type not in range(4) or not payload or value_size < 2:
        raise ValueError("Invalid proxy type, empty payload, or characteristic size")
    width = value_size - 1
    chunks = [payload[i:i + width] for i in range(0, len(payload), width)]
    if len(chunks) == 1:
        return [bytes([message_type]) + chunks[0]]
    return [bytes([(1 if i == 0 else 3 if i == len(chunks) - 1 else 2) << 6 | message_type]) + chunk
            for i, chunk in enumerate(chunks)]


class ProxyReassembler:
    """One instance per proxy connection; malformed sequences fail closed."""

    def __init__(self, max_size: int = 1024):
        self.max_size = max_size
        self.reset()

    def reset(self):
        self.message_type = None
        self.buffer = bytearray()
        self.last_at = None

    def feed(self, value: bytes, now: float | None = None) -> tuple[int, bytes] | None:
        now = monotonic() if now is None else now
        try:
            if len(value) < 2:
                raise ValueError("Empty proxy header or payload")
            sar, message_type = value[0] >> 6, value[0] & 63
            if message_type not in range(4):
                raise ValueError("Reserved proxy message type")
            if self.last_at is not None and now - self.last_at >= 20:
                raise ValueError("Proxy SAR timed out; reconnect before continuing")
            if sar in (0, 1):
                if self.message_type is not None:
                    raise ValueError("New proxy message interrupted incomplete message")
                self.message_type = message_type
            elif self.message_type != message_type:
                raise ValueError("Proxy continuation without matching first segment")
            self.buffer.extend(value[1:])
            if len(self.buffer) > self.max_size:
                raise ValueError("Proxy payload exceeds configured bound")
            self.last_at = now
            if sar in (0, 3):
                result = message_type, bytes(self.buffer)
                self.reset()
                return result
            return None
        except ValueError:
            self.reset()
            raise


@dataclass(frozen=True)
class SecureNetworkBeacon:
    flags: int
    network_id: bytes
    iv_index: int
    authentication: bytes

    @classmethod
    def parse(cls, payload: bytes):
        if len(payload) != 22 or payload[0] != 1:
            raise ValueError("Expected 22-byte Secure Network Beacon")
        if payload[1] & ~3:
            raise ValueError("Reserved beacon flags set")
        return cls(payload[1], payload[2:10], int.from_bytes(payload[10:14], "big"), payload[14:22])

    @property
    def key_refresh(self) -> bool:
        return bool(self.flags & 1)

    @property
    def iv_update(self) -> bool:
        return bool(self.flags & 2)
