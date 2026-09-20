"""Resolve public MeshCore regions against each packet's transport code.

Reference: MeshCore src/helpers/TransportKeyStore.cpp and RegionMap.cpp.
"""
import hashlib
import hmac


SCOPES = ('de', 'de-ni', 'de-ni-wf', 'bsmesh', 'de-mitte', 'de-nord', 'de-harz', 'de-ni-h')
SCOPE_KEYS = {name: hashlib.sha256(('#' + name).encode()).digest()[:16]
              for name in SCOPES}


def scope_label(decoded):
    if decoded.get('route_type') not in (0, 3):
        return 'Kein Scope'
    try:
        codes = bytes.fromhex(decoded['transport_code'])
        if len(codes) != 4:
            return 'Unbekannt'
        code = int.from_bytes(codes[:2], 'little')
        message = bytes([decoded['payload_type']]) + bytes.fromhex(decoded['payload_hex'])
    except (KeyError, TypeError, ValueError):
        return 'Unbekannt'
    matches = []
    for name, key in SCOPE_KEYS.items():
        calculated = int.from_bytes(hmac.digest(key, message, 'sha256')[:2], 'little')
        # MeshCore reserves 0x0000 and 0xFFFF.
        calculated = max(1, min(0xFFFE, calculated))
        if calculated == code:
            matches.append(name)
    if len(matches) == 1:
        return matches[0]
    if matches:
        return 'Mehrdeutig: ' + ' / '.join(matches)
    return f'Unbekannt (0x{code:04X})'
