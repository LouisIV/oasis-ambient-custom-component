import unittest
from oasis_commands import power, brightness, temperature, brightness_temperature, rgb


class CommandsTest(unittest.TestCase):
    def test_rgb_channel_order(self):
        self.assertEqual(rgb(0, 255, 0).hex(), 'c6e50200ff00')
        self.assertEqual(rgb(1, 2, 3).hex(), 'c6e502010203')
        with self.assertRaises(ValueError):
            rgb(256, 0, 0)

    def test_power(self):
        self.assertEqual(power(False).hex(), 'c3e50200')
        self.assertEqual(power(True).hex(), 'c3e50201')

    def test_brightness_seconds(self):
        self.assertEqual(brightness(1, epoch_seconds=0x12345678).hex(), 'c4e5020178563412')

    def test_temperature_little_endian(self):
        self.assertEqual(temperature(6500).hex(), 'c5e5026419')

    def test_combined_order_and_timestamp_wrap(self):
        self.assertEqual(brightness_temperature(100, 6500,
                         epoch_milliseconds=0x112345678).hex(), 'd2e50264196478563412')

    def test_invalid_arguments(self):
        for value in (-1, 101, True, 1.5):
            with self.assertRaises(ValueError):
                brightness(value)
        for value in (0, 2699, 6501, False):
            with self.assertRaises(ValueError):
                temperature(value)
        with self.assertRaises(ValueError):
            power(1)


if __name__ == '__main__':
    unittest.main()
