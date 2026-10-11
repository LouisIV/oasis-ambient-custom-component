"""Durable, serialized nonce/sequence allocation for one local mesh sender.

Never delete or restore this database while reusing a sender address/NetKey.
"""
import os
from pathlib import Path
import sqlite3


class SequenceStore:
    def __init__(self, path: Path, identity: str, source: int, iv_index: int, *, initialize=False):
        if not 1 <= source <= 0x7fff or not 0 <= iv_index <= 0xffffffff:
            raise ValueError("Invalid sender or IV index")
        if not path.exists():
            if not initialize:
                raise ValueError("Sender state missing; explicit initialization is required")
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS sender (singleton INTEGER PRIMARY KEY CHECK(singleton=1), identity TEXT, source INTEGER, iv INTEGER, next_sequence INTEGER)")
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute("SELECT identity,source,iv FROM sender WHERE singleton=1").fetchone()
            if row is None:
                if not initialize:
                    raise ValueError("Sender state empty; refusing to reset sequence")
                self.connection.execute("INSERT INTO sender VALUES(1,?,?,?,0)", (identity, source, iv_index))
            elif row != (identity, source, iv_index):
                raise ValueError("Sender identity/source/IV changed; explicit migration required")
            self.connection.execute("COMMIT")
        except BaseException:
            self.connection.execute("ROLLBACK")
            self.connection.close()
            raise

    def allocate(self) -> int:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            sequence = self.connection.execute("SELECT next_sequence FROM sender WHERE singleton=1").fetchone()[0]
            if sequence > 0xffffff:
                raise ValueError("Mesh sequence exhausted; IV update required")
            self.connection.execute("UPDATE sender SET next_sequence=? WHERE singleton=1", (sequence + 1,))
            self.connection.execute("COMMIT")
            return sequence
        except BaseException:
            self.connection.execute("ROLLBACK")
            raise

    def close(self):
        self.connection.close()
