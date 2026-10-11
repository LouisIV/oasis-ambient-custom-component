import unittest

from mesh_protocol import ProxyReassembler, SecureNetworkBeacon, fragment_proxy


class ProxyTests(unittest.TestCase):
    def test_real_oasis_beacon(self):
        parser = ProxyReassembler()
        self.assertIsNone(parser.feed(bytes.fromhex("4101003750844603aa121700000000e2d2870058"), now=0))
        kind, data = parser.feed(bytes.fromhex("c18e9301"), now=1)
        self.assertEqual(kind, 1)
        beacon = SecureNetworkBeacon.parse(data)
        self.assertEqual(beacon.network_id.hex(), "3750844603aa1217")
        self.assertEqual(beacon.iv_index, 0)
        self.assertFalse(beacon.key_refresh)
        self.assertFalse(beacon.iv_update)
        self.assertEqual(beacon.authentication.hex(), "e2d28700588e9301")
        self.assertEqual(fragment_proxy(kind, data), [
            bytes.fromhex("4101003750844603aa121700000000e2d2870058"), bytes.fromhex("c18e9301")])

    def test_roundtrip_sizes(self):
        for kind in range(4):
            for size in (1, 19, 20, 38, 39, 65, 384):
                for mtu in (20, 66, 244):
                    data = bytes(i % 256 for i in range(size))
                    parser = ProxyReassembler()
                    chunks = fragment_proxy(kind, data, mtu)
                    for chunk in chunks[:-1]:
                        self.assertLessEqual(len(chunk), mtu)
                        self.assertIsNone(parser.feed(chunk))
                    self.assertEqual(parser.feed(chunks[-1]), (kind, data))

    def test_malformed(self):
        for value in (b"", b"\x00", b"\x04a", b"\x80a", b"\xc0a"):
            with self.assertRaises(ValueError):
                ProxyReassembler().feed(value)

    def test_mismatch_and_interruption(self):
        for next_value in (b"\xc1b", b"\x00b", b"\x40b"):
            parser = ProxyReassembler()
            parser.feed(b"\x40a")
            with self.assertRaises(ValueError):
                parser.feed(next_value)
            self.assertIsNone(parser.message_type)

    def test_timeout_and_size_bound(self):
        parser = ProxyReassembler(max_size=2)
        parser.feed(b"\x40a", now=0)
        with self.assertRaises(ValueError):
            parser.feed(b"\xc0b", now=20)
        parser.feed(b"\x40a", now=21)
        with self.assertRaises(ValueError):
            parser.feed(b"\xc0bc", now=22)

    def test_bad_beacon(self):
        for value in (b"", bytes(22), b"\x01\x04" + bytes(20)):
            with self.assertRaises(ValueError):
                SecureNetworkBeacon.parse(value)


if __name__ == "__main__":
    unittest.main()
