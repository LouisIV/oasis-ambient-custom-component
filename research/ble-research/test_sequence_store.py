import tempfile
import unittest
from pathlib import Path
from sequence_store import SequenceStore


class SequenceTests(unittest.TestCase):
    def test_persistent_serialized_allocations(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sender.db"
            with self.assertRaises(ValueError):
                SequenceStore(path, "network", 0x7fff, 0)
            a = SequenceStore(path, "network", 0x7fff, 0, initialize=True)
            b = SequenceStore(path, "network", 0x7fff, 0)
            self.assertEqual(a.allocate(), 0)
            self.assertEqual(b.allocate(), 1)
            a.close()
            b.close()
            c = SequenceStore(path, "network", 0x7fff, 0, initialize=True)
            self.assertEqual(c.allocate(), 2)
            c.close()
            with self.assertRaises(ValueError):
                SequenceStore(path, "network", 0x7fff, 1)
            with self.assertRaises(ValueError):
                SequenceStore(path, "different", 0x7fff, 0)

    def test_exhaustion(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SequenceStore(Path(directory) / "sender.db", "network", 1, 0, initialize=True)
            store.connection.execute("UPDATE sender SET next_sequence=16777215")
            self.assertEqual(store.allocate(), 0xffffff)
            with self.assertRaises(ValueError):
                store.allocate()
            store.close()
