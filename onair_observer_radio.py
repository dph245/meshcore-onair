"""Normalize MQTT observer status and store radio profile observations in SQLite."""
import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

CORE_FIELDS = ('frequency_hz', 'bandwidth_hz', 'spreading_factor', 'coding_rate')
PUBLIC_KEY = re.compile(r'[0-9a-fA-F]{64}')
STATUS_TOPIC = re.compile(r'meshcore/(?:[a-z0-9]{3}|test)/([0-9a-f]{64})/status', re.IGNORECASE | re.ASCII)
NUMBER = re.compile(r'[+-]?[0-9]+(?:\.[0-9]+)?')
MAX_CLOCK_LEAD = 60
MIN_CLOCK_TIME = datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp()


def _text(value, limit=256):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > limit or value.casefold() in ('?', 'unknown', 'n/a'):
        return None
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        return None
    return value if value.isprintable() else None


def observer_identity(value):
    """Retain opaque legacy IDs and canonicalize full hexadecimal public keys."""
    value = _text(value)
    return value.lower() if value and PUBLIC_KEY.fullmatch(value) else value


def status_origin_id(data):
    payload_id = observer_identity(data.get('origin_id'))
    topic = STATUS_TOPIC.fullmatch(data.get('_mqtt_topic') or '')
    if topic and payload_id and payload_id != topic[1].lower():
        return None
    return payload_id or (topic[1].lower() if topic else None)


def _integer(value, minimum, maximum, multiplier=1):
    # Decimal conversion preserves the wire units without float rounding.
    if type(value) not in (str, int, float):
        return None
    value = str(value).strip()
    if len(value) > 32 or not NUMBER.fullmatch(value):
        return None
    try:
        number = Decimal(value) * multiplier
        if minimum <= number <= maximum and number == number.to_integral_value():
            return int(number)
    except InvalidOperation:
        pass
    return None


def _coding_rate(value):
    if isinstance(value, str) and value.strip().startswith('4/'):
        value = value.strip()[2:]
    return _integer(value, 5, 8)


def _sync_word(value):
    if isinstance(value, str) and re.fullmatch(r'0[xX][0-9a-fA-F]{1,4}', value.strip()):
        return int(value, 16)
    return _integer(value, 0, 65535)


def _parameters(data):
    radio = data.get('radio')
    profile = {}
    if isinstance(radio, str) and len(radio) <= 128:
        parts = radio.split(',')
        if len(parts) == 4:
            profile.update(zip(CORE_FIELDS, (
                _integer(parts[0], 1, 100_000_000_000, 1_000_000),
                _integer(parts[1], 1, 100_000_000, 1_000),
                _integer(parts[2], 5, 12),
                _coding_rate(parts[3]),
            )))
    elif isinstance(radio, dict):
        # Explicit-unit fields permit partial extensions without guessing magnitudes.
        profile.update(
            frequency_hz=_integer(radio.get('frequency_hz'), 1, 100_000_000_000),
            bandwidth_hz=_integer(radio.get('bandwidth_hz'), 1, 100_000_000),
            spreading_factor=_integer(radio.get('spreading_factor'), 5, 12),
            coding_rate=_coding_rate(radio.get('coding_rate')),
            tx_power_dbm=_integer(radio.get('tx_power_dbm'), -128, 127),
            preamble_length=_integer(radio.get('preamble_length'), 1, 65535),
            sync_word=_sync_word(radio.get('sync_word')),
            radio_ic=_text(radio.get('radio_ic'), 80),
        )
    firmware = _text(data.get('firmware'), 80)
    client = (_text(data.get('client_version'), 128) or '').partition('/')[0].lower()
    if firmware is None:
        if client == 'openhop_repeater' or data.get('model') == 'openHop-Repeater':
            firmware = 'openHop Repeater'
        elif client == 'meshcore':
            firmware = 'MeshCore'
    profile.update(firmware=firmware, firmware_version=_text(data.get('firmware_version'), 80))
    return {field: value for field, value in profile.items() if value is not None}


def status_timestamp(data):
    value = data.get('timestamp')
    if not isinstance(value, str):
        return None
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class RadioReport:
    origin_id: str
    origin: str | None
    reported_at: float | None
    received_at: float
    retained: bool
    parameters: dict


def radio_report(data, received_at=None):
    if received_at is None:
        received_at = data.get('_mqtt_received_at')
        if received_at is None:
            received_at = time.time()
    origin_id = status_origin_id(data)
    if origin_id is None or data.get('status') == 'offline':
        return None
    parameters = _parameters(data)
    if not parameters:
        return None

    retained = bool(data.get('_mqtt_retained'))
    source = status_timestamp(data)
    try:
        # Date-only values supply no observation time.
        reported_at = source.timestamp() if source and len(data['timestamp']) > 10 else None
    except (OverflowError, ValueError, OSError):
        reported_at = None
    if reported_at is not None and reported_at > received_at + MAX_CLOCK_LEAD:
        return None
    # MQTT can carry a boot-time clock near the Unix epoch before NTP is ready.
    if reported_at is not None and reported_at < MIN_CLOCK_TIME:
        reported_at = None
    if retained and reported_at is None:
        return None
    return RadioReport(origin_id, _text(data.get('origin')), reported_at, received_at,
                       retained, parameters)


HISTORY_SQL = '''CREATE TABLE IF NOT EXISTS observer_radio_history (
    origin_id TEXT NOT NULL,
    observed_at REAL NOT NULL,
    detected_at REAL NOT NULL,
    source_timestamp REAL,
    retained INTEGER NOT NULL,
    origin TEXT,
    profile TEXT NOT NULL,
    field_times TEXT NOT NULL,
    last_confirmed_at REAL NOT NULL,
    first_full_at REAL,
    last_full_at REAL,
    transition_after REAL,
    PRIMARY KEY (origin_id, observed_at)
) WITHOUT ROWID'''
CONFLICTS_SQL = '''CREATE TABLE IF NOT EXISTS observer_radio_conflicts (
    origin_id TEXT NOT NULL,
    observed_at REAL NOT NULL,
    unresolved_fields TEXT NOT NULL,
    resolved_at REAL,
    PRIMARY KEY (origin_id, observed_at)
) WITHOUT ROWID'''


def migrate_radio(db):
    db.execute(HISTORY_SQL)
    db.execute(CONFLICTS_SQL)
    db.execute('''CREATE UNIQUE INDEX IF NOT EXISTS observer_radio_open_conflict
        ON observer_radio_conflicts (origin_id) WHERE resolved_at IS NULL''')
    db.execute('PRAGMA user_version=17')


_LATEST = '''SELECT origin, profile, field_times, last_confirmed_at, observed_at,
    first_full_at, last_full_at FROM observer_radio_history
    WHERE origin_id=? ORDER BY observed_at DESC LIMIT 1'''
_AT = '''SELECT profile, observed_at, detected_at, first_full_at, last_full_at
    FROM observer_radio_history WHERE origin_id=? AND observed_at<=?
    ORDER BY observed_at DESC LIMIT 1'''
_NEXT = '''SELECT transition_after FROM observer_radio_history
    WHERE origin_id=? AND observed_at>? ORDER BY observed_at LIMIT 1'''
_OPEN_CONFLICT = '''SELECT observed_at, unresolved_fields FROM observer_radio_conflicts
    WHERE origin_id=? AND resolved_at IS NULL'''
_CONFLICT_AT = '''SELECT resolved_at FROM observer_radio_conflicts
    WHERE origin_id=? AND observed_at<=? ORDER BY observed_at DESC LIMIT 1'''


def _current(origin_id, origin, profile, times, last, ambiguous=False):
    return dict(origin_id=origin_id, origin=origin, profile=profile, field_times=times,
                last_confirmed_at=last, ambiguous=ambiguous)


def current_radio_profiles(db):
    result = {}
    rows = db.execute('''SELECT h.origin_id, origin, profile, field_times, last_confirmed_at
        FROM (SELECT origin_id, MAX(observed_at) AS observed_at
              FROM observer_radio_history GROUP BY origin_id) head
        JOIN observer_radio_history h USING (origin_id, observed_at)''')
    for origin_id, origin, profile, times, last in rows:
        ambiguous = db.execute(_OPEN_CONFLICT, (origin_id,)).fetchone() is not None
        result[origin_id] = _current(origin_id, origin, json.loads(profile), json.loads(times),
                                     last, ambiguous)
    return result


def record_radio(db, report):
    """Apply an ordered patch and return the new head after a material update."""
    identity, updates = report.origin_id, report.parameters
    observed = report.reported_at if report.reported_at is not None else report.received_at
    latest = db.execute(_LATEST, (identity,)).fetchone()
    ambiguous = False
    if latest:
        origin, raw, raw_times, last, first, first_full, last_full = latest
        if observed < last or (observed == last and report.retained):
            return None
        previous, times = json.loads(raw), json.loads(raw_times)
        conflict = db.execute(_OPEN_CONFLICT, (identity,)).fetchone()
        if observed == last:
            # A duplicate must not refresh fields or choose an order for two
            # different payloads carrying the same source timestamp.
            fields = {field for field, value in updates.items()
                      if times.get(field) == last and previous[field] != value}
            if fields and conflict is None:
                db.execute('INSERT INTO observer_radio_conflicts VALUES (?,?,?,NULL)',
                           (identity, last, json.dumps(sorted(fields))))
                return _current(identity, origin, previous, times, last, True)
            if fields:
                pending = set(json.loads(conflict[1]))
                if fields - pending:
                    db.execute('''UPDATE observer_radio_conflicts SET unresolved_fields=?
                        WHERE origin_id=? AND observed_at=?''',
                               (json.dumps(sorted(pending | fields)), identity, conflict[0]))
            return None
        if conflict:
            pending = set(json.loads(conflict[1]))
            remaining = pending - updates.keys()
            ambiguous = bool(remaining)
            if pending != remaining:
                db.execute('''UPDATE observer_radio_conflicts SET unresolved_fields=?, resolved_at=?
                    WHERE origin_id=? AND observed_at=?''',
                           (json.dumps(sorted(remaining)), None if ambiguous else observed,
                            identity, conflict[0]))
    else:
        origin, previous, times = None, {}, {}
        first_full = last_full = None

    # Only fields present and valid in this status acquire fresh evidence.
    profile = previous | updates
    changed_at = [times[field] for field in updates.keys() & previous.keys()
                  if previous[field] != updates[field]]
    origin = report.origin or origin
    times.update(dict.fromkeys(updates, observed))
    full = report.reported_at if all(field in updates for field in CORE_FIELDS) else None
    if profile != previous:
        transition = min(changed_at, default=None)
        db.execute('''INSERT INTO observer_radio_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (identity, observed, report.received_at, report.reported_at, report.retained,
                    origin, json.dumps(profile), json.dumps(times), observed, full, full, transition))
    else:
        db.execute('''UPDATE observer_radio_history SET origin=?, field_times=?, last_confirmed_at=?,
                      first_full_at=?, last_full_at=? WHERE origin_id=? AND observed_at=?''',
                   (origin, json.dumps(times), observed,
                    full if first_full is None else first_full,
                    full if full is not None else last_full, identity, first))
    return _current(identity, origin, profile, times, observed, ambiguous)


def radio_profile_at(db, origin_id, received_at):
    """Resolve an observer's reported profile at a Unix timestamp in UTC."""
    identity = observer_identity(origin_id)
    if identity is None or type(received_at) not in (int, float) or not math.isfinite(received_at):
        return dict(match='unknown', reason='no_observation')
    row = db.execute(_AT, (identity, received_at)).fetchone()
    if row is None:
        return dict(match='unknown', reason='no_observation')
    conflict = db.execute(_CONFLICT_AT, (identity, received_at)).fetchone()
    if conflict and (conflict[0] is None or received_at < conflict[0]):
        return dict(match='unknown', reason='conflicting_status')

    raw, observed, detected, first_full, last_full = row
    exact = received_at in (first_full, last_full)
    if not exact:
        following = db.execute(_NEXT, (identity, received_at)).fetchone()
        if following and following[0] is not None and received_at > following[0]:
            return dict(match='unknown', reason='transition')

    profile = json.loads(raw)
    if not any(field in profile for field in CORE_FIELDS):
        return dict(match='unknown', reason='no_radio_parameters')
    return dict(match='confirmed' if exact else 'last_known', profile=profile,
                observed_at=observed, detected_at=detected, known_valid_from=None)
