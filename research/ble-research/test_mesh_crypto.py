"""Official Bluetooth Mesh Protocol 1.1, sections 8.1 and 8.2 vectors.

These PUBLIC SAMPLE KEYS must never be used to provision real devices.
"""
import unittest

from mesh_crypto import (NetworkMessage, authenticate_beacon, beacon_key, cmac,
                         decrypt_network, encrypt_network, decrypt_access, encrypt_access, k1, k2, k3, k4, s1)
from cryptography.exceptions import InvalidTag

H = bytes.fromhex
NET = H("f7a2a44f8e8a8029064f173ddc1e2b00")
APP = H("3216d1509884b533248541792b877f98")


class CryptoTests(unittest.TestCase):
    def test_s1(self):
        self.assertEqual(s1(b"test").hex(), "b73cefbd641ef2ea598c2b6efb62f79c")

    def test_k1(self):
        self.assertEqual(k1(APP, H("2ba14ffa0df84a2831938d57d276cab4"),
                            H("5a09d60797eeb4478aada59db3352a0d")).hex(),
                         "f6ed15a8934afbe7d83e8dcb57fcf5d7")

    def test_k2(self):
        nid, encryption, privacy = k2(NET)
        self.assertEqual(nid, 0x7f)
        self.assertEqual(encryption.hex(), "9f589181a0f50de73c8070c7a6d27f46")
        self.assertEqual(privacy.hex(), "4c715bd4a64b938f99b453351653124f")

    def test_k2_friendship(self):
        nid, encryption, privacy = k2(NET, H("010203040506070809"))
        self.assertEqual(nid, 0x73)
        self.assertEqual(encryption.hex(), "11efec0642774992510fb5929646df49")
        self.assertEqual(privacy.hex(), "d4d7cc0dfa772d836a8df9df5510d7a7")

    def test_k3_k4(self):
        self.assertEqual(k3(NET).hex(), "ff046958233db014")
        self.assertEqual(k4(APP), 0x38)

    def test_beacon_key(self):
        self.assertEqual(beacon_key(H("7dd7364cd842ad18c17c2b820c84c3d6")).hex(),
                         "5423d967da639a99cb02231a83f7d254")

    def test_beacon_authentication_and_tampering(self):
        # Roundtrip supplements (does not replace) official derivation vectors.
        body = b"\x00" + k3(NET) + bytes(4)
        payload = b"\x01" + body + cmac(beacon_key(NET), body)[:8]
        self.assertTrue(authenticate_beacon(NET, payload))
        for offset in range(len(payload)):
            altered = bytearray(payload)
            altered[offset] ^= 1
            self.assertFalse(authenticate_beacon(NET, bytes(altered)))
        self.assertFalse(authenticate_beacon(APP, payload))
        self.assertFalse(authenticate_beacon(NET, b""))

    def test_reject_wrong_key_lengths(self):
        for function in (k2, k3, k4, beacon_key):
            for length in (0, 15, 17, 32):
                with self.assertRaises(ValueError):
                    function(bytes(length))

    def test_official_network_pdus(self):
        key = H("7dd7364cd842ad18c17c2b820c84c3d6")
        # Mesh Protocol 1.1 sections 8.3.1, 8.3.2, and first segment of 8.3.6.
        vectors = [
            (NetworkMessage(1, 0, 1, 0x1201, 0xfffd, H("034b50057e400000010000")),
             "68eca487516765b5e5bfdacbaf6cb7fb6bff871f035444ce83a670df"),
            (NetworkMessage(1, 0, 0x014820, 0x2345, 0x1201, H("04320308ba072f")),
             "68d4c826296d7979d7dbc0c9b4d43eebec129d20a620d01e"),
            (NetworkMessage(0, 4, 0x3129ab, 3, 0x1201, H("8026ac01ee9dddfd2169326d23f3afdf")),
             "68cab5c5348a230afba8c63d4e686364979deaf4fd40961145939cda0e")]
        for message, expected in vectors:
            pdu = encrypt_network(key, 0x12345678, message)
            self.assertEqual(pdu.hex(), expected)
            self.assertEqual(decrypt_network(key, 0x12345678, H(expected)), message)
            altered = pdu[:-1] + bytes([pdu[-1] ^ 1])
            with self.assertRaises(InvalidTag):
                decrypt_network(key, 0x12345678, altered)

    def test_official_unsegmented_access(self):
        # Bluetooth Mesh Protocol 1.1 section 8.3.16.
        key = H("9d6dd0e96eb25dc19a40ed9914f8f03f")
        access = H("800300563412")
        lower = encrypt_access(key, 0x12345678, 6, 0x1201, 3, access, device_key=True)
        self.assertEqual(lower.hex(), "0089511bf1d1a81c11dcef")
        message = NetworkMessage(0, 11, 6, 0x1201, 3, lower)
        self.assertEqual(decrypt_access(key, 0x12345678, message, device_key=True), access)

    def test_application_access_roundtrip(self):
        lower = encrypt_access(APP, 0, 5, 0x7fff, 2, H("c1e50201"))
        message = NetworkMessage(0, 5, 5, 0x7fff, 2, lower)
        self.assertEqual(decrypt_access(APP, 0, message), H("c1e50201"))
        with self.assertRaises(ValueError):
            decrypt_access(APP, 0, message, device_key=True)
        with self.assertRaises(ValueError):
            encrypt_access(APP, 0, 5, 0x7fff, 0x8000, b"a")


if __name__ == "__main__":
    unittest.main()
