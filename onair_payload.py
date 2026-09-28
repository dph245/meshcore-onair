"""Visible version-0 peer envelopes, acknowledgments and control data.

Wire layout: meshcore-dev/MeshCore src/Mesh.cpp and src/Utils.cpp.
The routing path outside the payload is not the encrypted PATH return path.
"""
from datetime import datetime, timezone

from onair_advert import NODE_TYPES

KINDS = {0: 'Anfrage', 1: 'Antwort', 2: 'Direktnachricht', 3: 'Bestätigung',
         7: 'Anonyme Anfrage', 8: 'Pfad-Rückgabe', 10: 'Multipart', 11: 'CONTROL'}


def decode_payload_details(decoded):
    kind = decoded.get('payload_type')
    if kind not in KINDS:
        return {}
    summary = KINDS[kind]
    fields = []
    result = {'payload_summary': summary, 'payload_fields': fields,
              'payload_status': None}
    if decoded.get('payload_ver', 0) != 0:
        result['payload_status'] = 'Nicht unterstützte Payload-Version'
        return result
    try:
        payload = bytes.fromhex(decoded.get('payload_hex', ''))
    except (ValueError, TypeError):
        result['payload_status'] = 'Ungültige Payload-Hexdaten'
        return result

    def field(label, value):
        fields.append({'label': label, 'value': str(value)})

    def invalid(message):
        result['payload_status'] = message
        return result

    if kind == 11:
        # MeshCore docs/payloads.md: CONTROL subtype is the upper nibble.
        field('CONTROL-Nutzdaten (Hex)', payload.hex())
        if not payload:
            return invalid('Unvollständiger CONTROL-Header')
        flags, subtype = payload[0], payload[0] >> 4
        field('Flags', f'0x{flags:02x}')
        field('CONTROL-Untertyp', f'0x{subtype:x}')
        names = {8: 'Node-Suche (DISCOVER_REQ)', 9: 'Suchantwort (DISCOVER_RESP)'}
        result['payload_summary'] = names.get(subtype, f'CONTROL · Untertyp 0x{subtype:x}')
        if subtype not in names:
            return invalid('Unbekannter CONTROL-Untertyp; Inhalt als Hexdaten verfügbar')
        if len(payload) < 6:
            return invalid('Unvollständiger Discovery-Header: mindestens 6 Byte erforderlich')
        tag = int.from_bytes(payload[2:6], 'little')
        field('Discovery-Tag (uint32, Little Endian)', f'0x{tag:08x}')
        if subtype == 8:
            node_filter = payload[1]
            types = [NODE_TYPES.get(n, f'Typ {n}') for n in range(8) if node_filter & (1 << n)]
            field('Gesuchte Node-Typen', f'{", ".join(types) or "Keine"} (0x{node_filter:02x})')
            field('Angeforderter Public Key', '8-Byte-Präfix' if flags & 1 else 'Vollständig (32 Byte)')
            result['payload_summary'] += f' · {", ".join(types) or "Keine Node-Typen"} · Tag 0x{tag:08x}'
            if 6 < len(payload) < 10:
                return invalid('Unvollständiger Since-Zeitstempel: 4 Byte erforderlich')
            since = int.from_bytes(payload[6:10], 'little') if len(payload) >= 10 else 0
            field('Geändert seit (UTC)', datetime.fromtimestamp(since, timezone.utc).isoformat()
                  if since else 'Keine Zeitbegrenzung (0)')
            if len(payload) > 10:
                field('Weitere CONTROL-Daten (Hex)', payload[10:].hex())
        else:
            node_type = flags & 15
            name = NODE_TYPES.get(node_type, f'Typ {node_type}')
            field('Node-Typ', f'{name} ({node_type})')
            snr = int.from_bytes(payload[1:2], 'little', signed=True) / 4
            field('SNR der Suchanfrage beim antwortenden Node', f'{snr:g} dB')
            key = payload[6:]
            if len(key) not in (8, 32):
                return invalid('Ungültige Discovery-Public-Key-Länge: 8 oder 32 Byte erforderlich')
            field('Public-Key-Präfix (8 Byte)' if len(key) == 8 else 'Public Key (32 Byte)', key.hex())
            result['payload_summary'] += f' · {name} {key[:8].hex()} · {snr:g} dB · Tag 0x{tag:08x}'
        return result

    if kind in (3, 10):
        if kind == 10:
            if not payload:
                return invalid('Unvollständiger Multipart-Header')
            subtype, remaining = payload[0] & 15, payload[0] >> 4
            field('Weitere Pakete', remaining)
            field('Enthaltener Payload-Typ', f'0x{subtype:02x}')
            payload = payload[1:]
            if subtype != 3:
                field('Nutzdaten (Hex)', payload.hex())
                return invalid('Multipart-Untertyp nicht unterstützt')
            result['payload_summary'] = 'Multipart-ACK'
        if len(payload) < 4:
            return invalid('Unvollständiges ACK: mindestens 4 Byte erforderlich')
        ack = payload[:4].hex()
        field('ACK-Hash (Wire-Reihenfolge)', ack)
        field('ACK-Wert (uint32, Little Endian)', f'0x{int.from_bytes(payload[:4], "little"):08x}')
        if payload[4:]:
            field('Weitere ACK-Daten (Hex)', payload[4:].hex())
        result['payload_summary'] += f' · ACK {ack}'
        return result

    anonymous = kind == 7
    prefix_size = 33 if anonymous else 2
    if payload:
        field('Ziel-Hash (1 Byte)', payload[:1].hex())
    if len(payload) >= prefix_size:
        field('Absender-Public-Key' if anonymous else 'Absender-Hash (1 Byte)',
              payload[1:prefix_size].hex())
        source = payload[1:prefix_size].hex()
        result['payload_summary'] += f' · {source[:8]} → {payload[:1].hex()} · verschlüsselt'
    if len(payload) < prefix_size + 2:
        return invalid('Unvollständiger Peer-Header / MAC')
    field('MAC (ungeprüft)', payload[prefix_size:prefix_size + 2].hex())
    encrypted = payload[prefix_size + 2:]
    field('Verschlüsselte Nutzdaten', f'{len(encrypted)} Byte')
    field('Chiffretext (Hex)', encrypted.hex())
    if not encrypted or len(encrypted) % 16:
        return invalid('Ungültige Chiffretext-Länge: positive Vielfache von 16 Byte erforderlich')
    hidden = {
        0: 'Request-Typ und Anfrageinhalt', 1: 'Antwortinhalt',
        2: 'Zeitstempel und Nachricht', 7: 'Anfrageinhalt',
        8: 'Zurückgemeldeter Pfad und mögliche eingebettete ACK-/Antwortdaten',
    }[kind]
    result['payload_status'] = (
        f'{hidden} sind verschlüsselt. Der gemeinsame Schlüssel der beteiligten Nodes '
        'ist erforderlich; Channel-Schlüssel reichen dafür nicht aus.'
    )
    if kind == 8:
        field('Pfad-Bedeutung', 'Der sichtbare Routing-Pfad gehört zu diesem Paket; '
              'der zurückgemeldete Pfad liegt im verschlüsselten Inhalt.')
    return result
