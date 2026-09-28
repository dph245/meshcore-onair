"""Passive TRACE correlation and per-route SNR history."""
from onair_payload import decode_payload_details
from onair_scopes import scope_label


WINDOW_SECONDS = 60


def trace_sessions(rows, names):
    sessions, active, identities = [], {}, {}
    ignored = 0

    def node(token):
        if token not in identities:
            matches = [key for key in names if key.startswith(token)]
            key = matches[0] if len(matches) == 1 else None
            identities[token] = dict(hash=token, public_key=key,
                                     name=names.get(key), ambiguous=len(matches) > 1)
        return identities[token]

    for row_id, received, packet in sorted(rows, key=lambda row: (row[1], row[0])):
        decoded = packet['decoded']
        event = decode_payload_details(decoded).get('trace')
        if packet.get('direction') != 'rx' or not event:
            ignored += 1
            continue
        scope = scope_label(decoded)
        route_key = (scope, event['flags'], tuple(event['route']))
        bucket = (event['tag'], event['auth_code'], route_key)
        session = active.get(bucket)
        if session is None or received - session['first_seen'] > WINDOW_SECONDS:
            session = dict(id=row_id, tag=event['tag'], scope=scope, route_key=route_key,
                           first_seen=received, last_seen=received, receptions=0,
                           observed_hops=0, observers={},
                           hops=[dict(node(token), snr_min=None, snr_max=None)
                                 for token in event['route']])
            sessions.append(session)
            active[bucket] = session
        session['last_seen'] = received
        session['receptions'] += 1
        observer = packet.get('origin_id') or ''
        session['observers'][observer] = packet.get('origin') or observer or 'Ohne Observer-ID'
        session['observed_hops'] = max(session['observed_hops'], len(event['snrs']))
        for hop, snr in zip(session['hops'], event['snrs']):
            hop['snr_min'] = snr if hop['snr_min'] is None else min(hop['snr_min'], snr)
            hop['snr_max'] = snr if hop['snr_max'] is None else max(hop['snr_max'], snr)
    histories = {}
    for session in sessions:
        route_key = session.pop('route_key')
        history = histories.setdefault(route_key, dict(
            id=session['id'], scope=session['scope'],
            route=[node(hop['hash']) for hop in session['hops']], points=[]))
        history['points'].append(dict(id=session['id'], time=session['first_seen'],
                                      tag=session['tag'],
                                      snr_min=[hop['snr_min'] for hop in session['hops']],
                                      snr_max=[hop['snr_max'] for hop in session['hops']]))
        measured = [(i + 1, hop['snr_min']) for i, hop in enumerate(session['hops'])
                    if hop['snr_min'] is not None]
        weakest = min((snr for _, snr in measured), default=None)
        session['weakest_snr'] = weakest
        session['weakest_hops'] = [i for i, snr in measured if snr == weakest]
        session['observers'] = [dict(id=key or None, name=value)
                                for key, value in session['observers'].items()]
    for history in histories.values():
        history['point_count'] = len(history['points'])
        history['points'] = history['points'][-200:]
    return (sorted(sessions, key=lambda s: (s['last_seen'], s['id']), reverse=True),
            sorted(histories.values(), key=lambda h: h['points'][-1]['time'], reverse=True), ignored)
