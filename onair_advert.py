"""Decode MeshCore v0 node advertisements (docs/payloads.md)."""
import struct
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


NODE_TYPES = {0: "Unbekannt", 1: "Chat", 2: "Repeater", 3: "Room-Server", 4: "Sensor"}


def decode_advert(payload):
    if len(payload) < 100:
        return {"advert": None, "advert_status": "Ungültige ADVERT-Payload: zu kurz"}
    advert = {
        "public_key": payload[:32].hex(),
        "timestamp": int.from_bytes(payload[32:36], "little"),
        "signature": payload[36:100].hex(),
        "signature_status": "Nicht geprüft",
        "flags": None, "node_type": None, "node_type_name": "Unbekannt",
        "name": None, "latitude": None, "longitude": None,
        "feature_1": None, "feature_2": None,
    }
    appdata = payload[100:]
    try:
        Ed25519PublicKey.from_public_bytes(payload[:32]).verify(payload[36:100], payload[:36] + appdata)
        advert["signature_status"] = "Gültig"
    except (InvalidSignature, ValueError):
        advert["signature_status"] = "Ungültig"
    if not appdata:
        return {"advert": advert, "advert_status": None}
    flags = appdata[0]
    advert.update(flags=flags, node_type=flags & 0x0F,
                  node_type_name=NODE_TYPES.get(flags & 0x0F, f"Typ {flags & 0x0F}"))
    offset = 1
    try:
        if flags & 0x10:
            lat, lon = struct.unpack_from("<ii", appdata, offset)
            offset += 8
            if not (-90_000_000 <= lat <= 90_000_000 and -180_000_000 <= lon <= 180_000_000):
                return {"advert": advert, "advert_status": "Ungültige ADVERT-Position"}
            advert.update(latitude=lat / 1_000_000, longitude=lon / 1_000_000)
        for mask, field in ((0x20, "feature_1"), (0x40, "feature_2")):
            if flags & mask:
                advert[field] = struct.unpack_from("<H", appdata, offset)[0]
                offset += 2
        if flags & 0x80:
            advert["name"] = appdata[offset:].split(b"\0", 1)[0].decode("utf-8")
    except struct.error:
        return {"advert": advert, "advert_status": "Ungültige ADVERT-Payload: Felder fehlen"}
    except UnicodeDecodeError:
        return {"advert": advert, "advert_status": "Ungültiger ADVERT-Name (UTF-8)"}
    return {"advert": advert, "advert_status": None}
