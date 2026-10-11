"""Local-only manual repeater administration. Never starts Archive or migrates a DB."""
import argparse
from contextlib import closing
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
import unicodedata


def public_key(value):
    if not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise ValueError('Public Key muss aus exakt 64 Hexzeichen bestehen.')
    return value.lower()


def validate(values):
    for field, limit in [('name', 128), ('source', 512)]:
        value = values[field].strip()
        if not value or len(value) > limit or any(unicodedata.category(c).startswith('C') for c in values[field]):
            raise ValueError(f'{field}: 1–{limit} Zeichen, keine Steuerzeichen.')
        values[field] = value
    for field, limit in [('latitude', 90), ('longitude', 180)]:
        value = float(values[field])
        if not math.isfinite(value) or abs(value) > limit:
            raise ValueError(f'{field}: endliche Zahl zwischen {-limit} und {limit} erforderlich.')
        values[field] = value
    if values['latitude'] == 0 and values['longitude'] == 0:
        raise ValueError('0/0 ist keine verwendbare Referenzposition.')
    return values


def describe(db, row):
    result = dict(row)
    observed = db.execute('SELECT * FROM nodes WHERE public_key=?', (row['public_key'],)).fetchone()
    received = db.execute('SELECT received FROM node_advert_paths WHERE public_key=?', (row['public_key'],)).fetchone()
    real_position = bool(observed and observed['latitude'] is not None and observed['longitude'] is not None
                         and math.isfinite(observed['latitude']) and math.isfinite(observed['longitude'])
                         and abs(observed['latitude']) <= 90 and abs(observed['longitude']) <= 180
                         and (observed['latitude'] != 0 or observed['longitude'] != 0))
    real_name = bool(observed and observed['name'])
    result.update(last_advert_received=received[0] if received else None,
                  last_advert='Last ADVERT: ' + str(received[0]) if received else 'Last ADVERT: None (manual)',
                  name_source='advert' if real_name else 'manual',
                  position_source='advert' if real_position else 'manual',
                  effective_name=observed['name'] if real_name else row['name'],
                  effective_latitude=observed['latitude'] if real_position else row['latitude'],
                  effective_longitude=observed['longitude'] if real_position else row['longitude'])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default=os.environ.get('ONAIR_DB_PATH'))
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('list')
    for command in ['add', 'show', 'update', 'delete']:
        sub = commands.add_parser(command)
        sub.add_argument('public_key')
        if command in ('add', 'update'):
            for field in ['name', 'latitude', 'longitude', 'source']:
                sub.add_argument('--' + field, required=command == 'add')
    args = parser.parse_args(argv)
    try:
        if not args.db:
            raise ValueError('--db oder ONAIR_DB_PATH ist erforderlich.')
        path = Path(args.db).expanduser().resolve()
        key = public_key(args.public_key) if hasattr(args, 'public_key') else None
        writing = args.command in ('add', 'update', 'delete')
        # mode=rw (not rwc) refuses missing files, including races after path checking.
        with closing(sqlite3.connect(path.as_uri() + ('?mode=rw' if writing else '?mode=ro'),
                                     uri=True, timeout=5)) as db:
            db.row_factory = sqlite3.Row
            if not writing:
                db.execute('PRAGMA query_only=ON')
            with db:
                db.execute('BEGIN IMMEDIATE' if writing else 'BEGIN')
                if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='manual_nodes'").fetchone():
                    raise ValueError('Schema manual_nodes fehlt. Zuerst die reguläre Anwendungsmigration durchführen.')
                old = db.execute('SELECT * FROM manual_nodes WHERE public_key=?', (key,)).fetchone() if key else None
                if args.command == 'list':
                    result = [describe(db, row) for row in db.execute('SELECT * FROM manual_nodes ORDER BY public_key')]
                elif args.command == 'show':
                    if old is None:
                        raise ValueError('Manueller Eintrag nicht gefunden.')
                    result = describe(db, old)
                elif args.command == 'delete':
                    if old is None:
                        raise ValueError('Manueller Eintrag nicht gefunden.')
                    db.execute('DELETE FROM manual_nodes WHERE public_key=?', (key,))
                    result = {'deleted': key}
                else:
                    if args.command == 'add' and old is not None:
                        raise ValueError('Manueller Eintrag existiert bereits; update verwenden.')
                    if args.command == 'update' and old is None:
                        raise ValueError('Manueller Eintrag nicht gefunden.')
                    fields = ['name', 'latitude', 'longitude', 'source']
                    if args.command == 'update' and not any(getattr(args, f) is not None for f in fields):
                        raise ValueError('Mindestens ein zu änderndes Feld angeben.')
                    values = validate({f: getattr(args, f) if getattr(args, f) is not None else old[f] for f in fields})
                    now = time.time()
                    if old is None:
                        db.execute('INSERT INTO manual_nodes VALUES(?,?,?,?,?,?,?)',
                                   (key, values['name'], values['latitude'], values['longitude'], values['source'], now, now))
                    else:
                        db.execute('UPDATE manual_nodes SET name=?,latitude=?,longitude=?,source=?,updated_at=? WHERE public_key=?',
                                   (values['name'], values['latitude'], values['longitude'], values['source'], now, key))
                    result = describe(db, db.execute('SELECT * FROM manual_nodes WHERE public_key=?', (key,)).fetchone())
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValueError, sqlite3.Error, OSError) as error:
        print(f'Fehler: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
