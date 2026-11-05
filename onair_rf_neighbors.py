"""Gessaman RF neighbor snapshots, independent of flood-path adjacency.

Reference: agessaman/MeshCore c2c4cb59e34c9d305a23bfc5d30f16c6fc3e30b2,
MQTTTopicRouter.h, MQTTPayloadBuilder.cpp and simple_repeater/MyMesh.cpp.
Scope strings are preserved as reported; an empty string is not proof that a
node has no scopes (in particular after a timeout or send failure).
"""
from datetime import datetime, timezone
import json
import math
import re


_TOPIC = re.compile(r'meshcore/([A-Za-z0-9]{3})/([0-9A-Fa-f]{64})/neighbors')
_KEY = re.compile(r'[0-9A-Fa-f]{64}')


def topic_identity(topic):
    match = _TOPIC.fullmatch(topic)
    return (match[1], match[2].lower()) if match else None


def _string(data, field):
    value = data.get(field)
    if value is not None and not isinstance(value, str):
        raise ValueError(f'{field}: expected string or null')
    if value is not None:
        value.encode('utf-8')  # Reject lone JSON surrogates before SQLite binding.
    return value


def _count(data, field):
    value = data.get(field)
    if value is not None and (type(value) is not int or not 0 <= value <= 0xFFFFFFFF):
        raise ValueError(f'{field}: expected uint32 or null')
    return value


def _reject_constant(value):
    raise ValueError('non-finite JSON number')


def parse_report(payload, observer_key):
    """Validate a snapshot atomically. Unknown extra fields survive in raw data.

    Optional absent/null fields stay unknown, including completeness. The topic
    supplies observer identity; a conflicting payload identity is rejected.
    Heard ages refer to the source snapshot time, never MQTT receipt time.
    """
    data = json.loads(payload.decode('utf-8'), parse_constant=_reject_constant)
    if not isinstance(data, dict) or not isinstance(data.get('neighbors'), list):
        raise ValueError('expected report object with neighbors array')
    origin_id = _string(data, 'origin_id')
    if origin_id is not None and (not _KEY.fullmatch(origin_id) or origin_id.lower() != observer_key):
        raise ValueError('origin_id does not match topic observer')
    timestamp = _string(data, 'timestamp')
    reported_at = None
    if timestamp is not None:
        try:
            stamp = datetime.fromisoformat(timestamp)
            # Offsetless observer timestamps are UTC, as in the status path.
            reported_at = stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).timestamp()
        except (ValueError, OverflowError, OSError):
            raise ValueError('timestamp: invalid source time') from None
    truncated = data.get('truncated')
    if truncated is not None and type(truncated) is not bool:
        raise ValueError('truncated: expected boolean or null')
    own = data.get('self', {})
    if not isinstance(own, dict):
        raise ValueError('self: expected object')
    report = dict(origin=_string(data, 'origin'), origin_id=origin_id,
                  source_timestamp=timestamp, reported_at=reported_at,
                  self_scopes=_string(own, 'scopes'),
                  self_default_scope=_string(own, 'default_scope'),
                  total_neighbors=_count(data, 'total_neighbors'),
                  queried_neighbors=_count(data, 'queried_neighbors'),
                  truncated=truncated)
    entries = []
    for item in data['neighbors']:
        if not isinstance(item, dict):
            raise ValueError('neighbor: expected object')
        key = _string(item, 'pubkey')
        if key is None or not _KEY.fullmatch(key):
            raise ValueError('pubkey: expected 64 hex characters')
        snr = item.get('snr')
        if snr is not None and (type(snr) not in (int, float) or not math.isfinite(snr)):
            raise ValueError('snr: expected finite number or null')
        if snr is not None:
            snr = float(snr)  # Bind as SQLite REAL, including large JSON integers.
        age = _count(item, 'heard_secs_ago')
        entries.append(dict(pubkey=key.lower(), snr=snr, heard_secs_ago=age,
                            heard_at=reported_at - age if reported_at is not None and age is not None else None,
                            scopes=_string(item, 'scopes'), status=_string(item, 'status')))
    return report, entries
