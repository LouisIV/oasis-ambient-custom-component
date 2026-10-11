"""Test the shipped protocol files without importing Home Assistant itself."""
import importlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'custom_components/oasis_ambient'))
for name in ('mesh_crypto', 'mesh_protocol', 'sequence_store', 'oasis_commands', 'oasis_controller'):
    sys.modules[name] = importlib.import_module(f'protocol.{name}')
suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'), pattern='test_*.py')
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(not result.wasSuccessful())
