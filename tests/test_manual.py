"""Manual administration writes only temporary databases; no live services."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from onair_archive import Archive
from onair_manual import main
from onair_replay import replay_response

KEY = '36477e' + 'a' * 58


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'archive.db'
        self.archive = Archive(self.path)
        self.archive.close()

    def cli(self, *args, code=0):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = main(['--db', str(self.path), *args])
        self.assertEqual(status, code, err.getvalue())
        return json.loads(out.getvalue()) if status == 0 else err.getvalue()

    def add(self, key=KEY, **overrides):
        fields = dict(name='Burgdorf Test', latitude='52.45', longitude='10.01', source='Betreiber')
        fields.update(overrides)
        args = ['add', key]
        for k, v in fields.items():
            args.extend(['--' + k, v])
        return self.cli(*args)

    def real_dump(self):
        with self.archive.connect() as db:
            return [line for line in db.iterdump() if not line.startswith('INSERT INTO "manual_nodes"')]

    def test_crud_and_no_real_data_changes(self):
        before = self.real_dump()
        added = self.add(KEY.upper())
        self.assertEqual(added['public_key'], KEY)
        self.assertEqual(added['last_advert'], 'Last ADVERT: None (manual)')
        self.assertEqual(added['position_source'], 'manual')
        self.assertEqual(len(self.cli('list')), 1)
        self.assertEqual(self.cli('show', KEY)['source'], 'Betreiber')
        changed = self.cli('update', KEY, '--name', 'Neuer Name', '--latitude', '53')
        self.assertEqual(changed['created_at'], added['created_at'])
        self.assertGreaterEqual(changed['updated_at'], added['updated_at'])
        self.assertEqual(changed['effective_latitude'], 53)
        bootstrap = self.archive.mesh_live_nodes()
        self.assertEqual(bootstrap['nodes'], [])
        self.assertEqual(bootstrap['manual_nodes'][0]['name'], 'Neuer Name')
        self.assertEqual(before, self.real_dump())
        self.cli('delete', KEY)
        self.assertEqual(self.archive.mesh_live_nodes()['manual_nodes'], [])
        self.assertEqual(before, self.real_dump())
        self.cli('show', KEY, code=1)
        self.cli('delete', KEY, code=1)
        self.cli('update', KEY, '--name', 'x', code=1)

    def test_validation_duplicates_and_atomic_updates(self):
        self.add()
        self.cli('add', KEY.upper(), '--name', 'x', '--latitude', '1', '--longitude', '2', '--source', 'x', code=1)
        for key in ['36477e', 'x'*64, 'a'*63, 'a'*65, ' '+KEY]:
            self.cli('show', key, code=1)
        for field, value in [('name', ''), ('name', 'a'*129), ('name', 'x\ny'),
                             ('source', ' '), ('source', 'x'*513), ('latitude', 'nan'),
                             ('longitude', 'inf'), ('latitude', '91'), ('longitude', '-181')]:
            self.cli('update', KEY, '--'+field+'='+value, code=1)
        self.cli('update', KEY, '--latitude', '0', '--longitude', '0', code=1)
        self.cli('update', KEY, code=1)
        self.assertEqual(self.cli('show', KEY)['name'], 'Burgdorf Test')

    def test_database_is_never_created_or_migrated_by_cli(self):
        self.path = Path(self.tmp.name) / 'absent.db'
        self.cli('list', code=1)
        self.assertFalse(self.path.exists())
        with patch.dict(os.environ, {}, clear=True), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['list']), 1)
        with self.archive.connect() as db, db:
            db.execute('DROP TABLE manual_nodes')
            db.execute('PRAGMA user_version=11')
        self.path = self.archive.path
        self.cli('list', code=1)
        with self.archive.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 11)

    def test_regular_migration_and_environment_path(self):
        with self.archive.connect() as db, db:
            db.execute('DROP TABLE manual_nodes')
            db.execute('PRAGMA user_version=11')
        upgraded = Archive(self.path)
        upgraded.close()
        with upgraded.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 14)
        with patch.dict(os.environ, {'ONAIR_DB_PATH': str(self.path)}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['list']), 0)

    def test_real_advert_fallback_and_delete_preserves_real(self):
        self.add()
        packet = {'direction':'rx', 'received_at':'2026-10-11T05:00:00+00:00',
                  'decoded':{'advert':{'public_key':KEY,'name':'Echter Name', 'node_type':2,
                             'timestamp':100,'signature_status':'Gültig','latitude':None,'longitude':None}}}
        with self.archive.connect() as db, db:
            self.archive._record_node(db, packet)
            self.archive._record_advert_path(db, packet)
        result = self.cli('show', KEY)
        self.assertEqual((result['name_source'], result['position_source']), ('advert', 'manual'))
        packet['decoded']['advert'].update(latitude=54, longitude=11, timestamp=101)
        with self.archive.connect() as db, db:
            self.archive._record_node(db, packet)
        result = self.cli('update', KEY, '--latitude', '55')
        self.assertEqual((result['effective_latitude'], result['position_source']), (54, 'advert'))
        before = self.real_dump()
        self.cli('delete', KEY)
        self.assertEqual(before, self.real_dump())

    def test_replay_snapshot_is_identical_with_manual_nodes(self):
        with patch('onair_replay.time.time', return_value=1791697200):
            before = replay_response(self.archive.connect)
            self.add()
            self.assertEqual(before, replay_response(self.archive.connect))
            self.cli('update', KEY, '--latitude', '53')
            self.assertEqual(before, replay_response(self.archive.connect))
            self.cli('delete', KEY)
            self.assertEqual(before, replay_response(self.archive.connect))
