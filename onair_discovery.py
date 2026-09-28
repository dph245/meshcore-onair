"""Passive discovery sessions; tag/time correlation does not identify a requester."""
from onair_payload import decode_payload_details
from onair_scopes import scope_label


WINDOW_SECONDS = 60


def discovery_sessions(rows, names):
    sessions, active = [], {}
    ignored = 0
    for row_id, received, packet in sorted(rows, key=lambda row: (row[1], row[0])):
        decoded = packet['decoded']
        event = decode_payload_details(decoded).get('discovery')
        if packet.get('direction') != 'rx' or not event:
            ignored += 1
            continue
        scope = scope_label(decoded)
        bucket = (event['tag'], scope)
        session = active.get(bucket)
        request = event if event['kind'] == 'request' else None
        # Reused tags outside the fixed window or different requests stay separate.
        if (session is None or received - session['first_seen'] > WINDOW_SECONDS
                or (request and session['request'] and request != session['request'])):
            session = dict(id=row_id, tag=event['tag'], scope=scope, first_seen=received,
                           last_seen=received, request=None, request_receptions=0,
                           receptions=0, responses={}, observers={})
            sessions.append(session)
            active[bucket] = session
        session['last_seen'] = received
        session['receptions'] += 1
        observer = packet.get('origin_id') or ''
        session['observers'][observer] = packet.get('origin') or observer or 'Ohne Observer-ID'
        if request:
            session['request'] = request
            session['request_receptions'] += 1
            continue
        key = event['public_key']
        # Never expand an ambiguous prefix or invent a name from discovery data.
        matches = [known for known in names if known.startswith(key)]
        identity = matches[0] if len(matches) == 1 else key
        response = session['responses'].setdefault(identity, dict(
            public_key=identity, name=names.get(identity), ambiguous=len(matches) > 1,
            node_type=event['node_type_name'], snr_min=event['snr'], snr_max=event['snr'],
            receptions=0))
        response['snr_min'] = min(response['snr_min'], event['snr'])
        response['snr_max'] = max(response['snr_max'], event['snr'])
        response['receptions'] += 1
    for session in sessions:
        session['responses'] = sorted(session['responses'].values(),
                                      key=lambda r: (-r['snr_max'], r['public_key']))
        session['unknown_nodes'] = sum(not r['name'] for r in session['responses'])
        session['observers'] = [dict(id=key or None, name=value)
                                for key, value in session['observers'].items()]
    return sorted(sessions, key=lambda s: (s['last_seen'], s['id']), reverse=True), ignored
