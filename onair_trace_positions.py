"""Resolve TRACE locations from signed ADVERTs on the OnAir reception timeline."""
from bisect import bisect_right
from collections import OrderedDict, defaultdict
import json
from math import isfinite
import os

from onair_neighbors import distance_km
from onair_positions import ADVERT_WHERE, KEY_EXPR

DEFAULT_TOLERANCE_M = 25
QUIET_SECONDS = 6 * 3600
POSITION_CACHE_KEYS = 256
MAX_CATCHUP_PACKETS = 10000

STAMP_EXPR = "json_extract(packet_json,'$.decoded.advert.timestamp')"
LAT_EXPR = "json_extract(packet_json,'$.decoded.advert.latitude')"
LON_EXPR = "json_extract(packet_json,'$.decoded.advert.longitude')"
ADVERT_SELECT = f'''SELECT {KEY_EXPR},received,id,{STAMP_EXPR},{LAT_EXPR},{LON_EXPR}
    FROM packets INDEXED BY {{index}}
    WHERE {ADVERT_WHERE} AND {{selection}}
    AND json_extract(packet_json,'$.decoded.advert.signature_status')='Gültig'
    AND {LAT_EXPR} BETWEEN -90 AND 90 AND {LON_EXPR} BETWEEN -180 AND 180
    AND ({LAT_EXPR}<>0 OR {LON_EXPR}<>0)'''

POSITION_EVIDENCE_SQL = ADVERT_SELECT.format(index='packets_advert_key_received',
    selection=KEY_EXPR + ' IN (SELECT value FROM json_each(?))')
NEW_EVIDENCE_SQL = ADVERT_SELECT.format(index='packets_kind_id', selection='id>? AND id<=?')


def _evidence(rows):
    for key, received, ident, stamp, lat, lon in rows:
        if isinstance(stamp, int):
            yield key, (received, ident, stamp, lat, lon)


def _near(a, b, tolerance_km):
    if a == b:
        return True
    return distance_km(dict(latitude=a[0], longitude=a[1]),
                       dict(latitude=b[0], longitude=b[1])) <= tolerance_km


class PositionTimeline:
    def __init__(self, rows, tolerance_km):
        self.times = []
        self.states = []
        by_stamp = defaultdict(dict)
        anchor = None
        issue = None
        last_received = competing_at = None
        candidate_stamp = None
        for received, _, stamp, lat, lon in sorted(rows):
            point = (lat, lon)
            seen = by_stamp[stamp]
            fresh = point not in seen
            opposing = [when for other, when in seen.items() if not _near(point, other, tolerance_km)]
            recent_tie = fresh and opposing and received - max(opposing) <= QUIET_SECONDS
            seen[point] = received
            if anchor is None:
                anchor = point
            elif not _near(anchor, point, tolerance_km) or recent_tie:
                competing_at = last_received
                anchor = point
                candidate_stamp = stamp if fresh else None
                if opposing or received - competing_at <= QUIET_SECONDS or issue == 'position_conflict':
                    issue = 'position_conflict'
                else:
                    issue = 'position_unconfirmed'
            elif issue and fresh and (candidate_stamp is None or stamp > candidate_stamp):
                if candidate_stamp is not None and received - competing_at >= QUIET_SECONDS:
                    issue = None
                candidate_stamp = stamp
            last_received = received
            state = (None, issue) if issue else (dict(latitude=anchor[0], longitude=anchor[1]), None)
            if not self.states or self.states[-1] != state:
                self.times.append(received)
                self.states.append(state)

    def at(self, stamp):
        index = bisect_right(self.times, stamp) - 1
        if index < 0:
            return None, 'missing_position'
        point, issue = self.states[index]
        if issue == 'position_conflict' and index < len(self.states) - 1:
            issue = 'historical_position_conflict'
        return point, issue


class TracePositionCache:
    """One archive's evidence, shared under the archive's historical query lock."""
    def __init__(self, tolerance_m=None, *, attached_source=False):
        self.tolerance_m = float(os.environ.get('ONAIR_TRACE_POSITION_TOLERANCE_M', DEFAULT_TOLERANCE_M)
                                 if tolerance_m is None else tolerance_m)
        if not isfinite(self.tolerance_m) or self.tolerance_m < 0:
            raise ValueError('ONAIR_TRACE_POSITION_TOLERANCE_M muss endlich und nicht negativ sein.')
        self.entries = OrderedDict()
        self.revision = None
        self.high = 0
        # Offline benchmarks attach the raw archive read-only behind temporary views.
        self.evidence_sql = POSITION_EVIDENCE_SQL
        self.new_sql = NEW_EVIDENCE_SQL
        if attached_source:
            self.evidence_sql = self.evidence_sql.replace('FROM packets', 'FROM source.packets')
            self.new_sql = self.new_sql.replace('FROM packets', 'FROM source.packets')

    def _catch_up(self, db):
        revision = db.execute('SELECT archive_epoch,source_revision FROM position_active').fetchone()
        high = db.execute('SELECT COALESCE(MAX(id),0) FROM packets').fetchone()[0]
        if (revision is None or revision != self.revision or high < self.high
                or high - self.high > MAX_CATCHUP_PACKETS):
            self.entries.clear()
        elif high > self.high and self.entries:
            additions = defaultdict(list)
            for key, row in _evidence(db.execute(self.new_sql, (self.high, high))):
                if key in self.entries:
                    additions[key].append(row)
            updated = {key: self._entry(self.entries[key][0] + rows) for key, rows in additions.items()}
            self.entries.update(updated)
        self.revision, self.high = revision, high

    def _entry(self, rows):
        return rows, PositionTimeline(rows, self.tolerance_m / 1000)

    def load(self, db, keys):
        if not keys:
            return {}
        self._catch_up(db)
        missing = keys - self.entries.keys()
        if missing:
            rows = defaultdict(list)
            for key, row in _evidence(db.execute(self.evidence_sql, (json.dumps(sorted(missing)),))):
                rows[key].append(row)
            self.entries.update({key: self._entry(rows[key]) for key in sorted(missing)})
        timelines = {}
        for key in sorted(keys):
            self.entries.move_to_end(key)
            timelines[key] = self.entries[key][1]
        while len(self.entries) > POSITION_CACHE_KEYS:
            self.entries.popitem(last=False)
        return timelines
