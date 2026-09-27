"""Visible version-0 peer envelopes and acknowledgments (no peer secrets).

Wire layout: meshcore-dev/MeshCore src/Mesh.cpp and src/Utils.cpp.
The routing path outside the payload is not the encrypted PATH return path.
"""

KINDS = {0: 'Anfrage', 1: 'Antwort', 2: 'Direktnachricht', 3: 'Bestätigung',
         7: 'Anonyme Anfrage', 8: 'Pfad-Rückgabe', 10: 'Multipart'}


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
