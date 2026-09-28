"""Temporary persisted node names, loaded through the production resolver."""
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import onair_mqtt as mqtt
from onair_archive import Archive


def seed_nodes(path, nodes):
    """Seed full public keys without adding receptions to packet statistics."""
    archive = Archive(path)
    archive.close()
    with archive.connect() as db, db:
        db.executemany('''INSERT INTO nodes
            (public_key, name, advert_time, first_seen, last_seen)
            VALUES (?, ?, 0, 0, 0)''', nodes.items())


@contextmanager
def node_database(nodes):
    with TemporaryDirectory() as folder:
        path = Path(folder) / 'nodes.sqlite3'
        seed_nodes(path, nodes)
        archive = Archive(path)
        try:
            with patch.object(mqtt, 'ALIASES', {}), \
                    patch.object(mqtt, 'learned_alias', archive.resolve):
                yield archive
        finally:
            archive.close()
