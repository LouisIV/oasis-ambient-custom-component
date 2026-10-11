"""APK-derived Oasis vendor access messages (not raw GATT writes).

Power, brightness, and combined CCT were physically verified on firmware
2.32.1. Brightness-only timestamps use seconds; combined uses milliseconds.
See apk-research/AOT-BLE-REPORT.txt for byte-level derivation.
"""
import struct
import time


def _integer(value, minimum, maximum, name):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(f'{name} must be an integer in {minimum}..{maximum}')
    return value


def power(on: bool) -> bytes:
    if type(on) is not bool:
        raise ValueError('Power must be a boolean')
    return bytes.fromhex('c3e502') + bytes([int(on)])


def rgb(red: int, green: int, blue: int) -> bytes:
    values = [_integer(value, 0, 255, name) for value, name in
              ((red, 'Red'), (green, 'Green'), (blue, 'Blue'))]
    return bytes.fromhex('c6e502') + bytes(values)


def color_mode(rgb_mode: bool) -> bytes:
    if type(rgb_mode) is not bool:
        raise ValueError('Mode selection must be boolean')
    return bytes.fromhex('cce502') + bytes([1 if rgb_mode else 2])


def brightness(percent: int, *, epoch_seconds=None) -> bytes:
    percent = _integer(percent, 0, 100, 'Brightness')
    if epoch_seconds is None:
        epoch_seconds = int(time.time())
    _integer(epoch_seconds, 0, 0xffffffff, 'Epoch seconds')
    return bytes.fromhex('c4e502') + struct.pack('<BI', percent, epoch_seconds)


def temperature(kelvin: int) -> bytes:
    kelvin = _integer(kelvin, 2700, 6500, 'Temperature')
    return bytes.fromhex('c5e502') + struct.pack('<H', kelvin)


def brightness_temperature(percent: int, kelvin: int, *, epoch_milliseconds=None) -> bytes:
    percent = _integer(percent, 0, 100, 'Brightness')
    kelvin = _integer(kelvin, 2700, 6500, 'Temperature')
    if epoch_milliseconds is None:
        epoch_milliseconds = time.time_ns() // 1_000_000
    if type(epoch_milliseconds) is not int or epoch_milliseconds < 0:
        raise ValueError('Epoch milliseconds must be a nonnegative integer')
    return bytes.fromhex('d2e502') + struct.pack('<HBI', kelvin, percent,
                                               epoch_milliseconds & 0xffffffff)
