import json
import math
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from onair_channels import decode_group_text
from onair_advert import decode_advert
from onair_scopes import scope_label


# ============================================================
# Konfiguration
# ============================================================

BROKER_HOST = "192.168.88.40"
BROKER_PORT = 1883
MQTT_TOPIC = "meshcore/#"

SHOW_STATUS = True
SHOW_TX = False


# Bekannte Nodes.
#
# Wichtig:
# Wir mappen bewusst erst ab 2 Byte.
# Ein 1-Byte-Hash wie "6f" ist zu kurz und kann mehrdeutig sein.
#
# Ein längerer Hash wie "6f33a9" matcht trotzdem auf "6f33".
ALIASES = {
    "8dbc": "TjülüTjülü",
    "dd4c": "Funkfeuer",
    "abba": "DatenScheune"
}


ROUTE_NAMES = {
    0: "TC_FLOOD",
    1: "FLOOD",
    2: "DIRECT",
    3: "TC_DIRECT",
}


PAYLOAD_NAMES = {
    0x00: "REQ",
    0x01: "RESPONSE",
    0x02: "TEXT_MSG",
    0x03: "ACK",
    0x04: "ADVERT",
    0x05: "GRP_TXT",
    0x06: "GRP_DATA",
    0x07: "ANON_REQ",
    0x08: "PATH",
    0x09: "TRACE",
    0x0A: "MULTIPART",
    0x0B: "CONTROL",
    0x0F: "RAW_CUSTOM",
}


# ============================================================
# Laufzeitstatus
# ============================================================

packet_number = 0

# MQTT/Observer-Hash:
#
# {
#     "4451F97B8F8B0DDC": {
#         "count": 3,
#         "first_number": 12
#     }
# }
seen_hashes = OrderedDict()
MAX_SEEN_HASHES = 5000

last_noise_floor = {}
learned_alias = None


# ============================================================
# Hilfsfunktionen
# ============================================================

def node_label(token):
    """
    Ersetzt bekannte Hop-Hashes durch lesbare Namen.

    Beispiel:
        dd4c   -> Funkfeuer[dd4c]
        8dbc81 -> TjülüTjülü[8dbc81]

    1-Byte-Hashes werden absichtlich nicht aufgelöst.
    """

    token = token.lower()
    if len(token) < 4:
        return token

    for prefix, name in ALIASES.items():
        prefix = prefix.lower()

        if len(token) >= len(prefix) and token.startswith(prefix):
            return f"{name}[{token}]"

    name = learned_alias(token) if learned_alias else None
    return f"{name}[{token}]" if name else token


def parse_float(value):
    if value is None:
        return None

    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def parse_int(value):
    if value is None:
        return None

    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def noise_sample(data):
    """Keep integer status readings unchanged, timestamped on local receipt."""
    stats = data.get('stats')
    value = stats.get('noise_floor') if isinstance(stats, dict) else None
    if isinstance(value, bool):
        return None
    number = parse_float(value)
    if number is None or not number.is_integer():
        return None
    sample = {'received_at': datetime.now().astimezone().isoformat(),
              'noise_floor': int(number)}
    timestamp = data.get('timestamp')
    try:
        status_at = datetime.fromisoformat(timestamp) if isinstance(timestamp, str) else None
    except ValueError:
        status_at = None
    if status_at is not None:
        # Observer timestamps without an offset are UTC, not browser local time.
        if status_at.tzinfo is None:
            status_at = status_at.replace(tzinfo=timezone.utc)
        sample['status_at'] = status_at.isoformat()
    elif data.get('_mqtt_retained'):
        # A retained message without a usable source time cannot prove activity.
        return None
    for field in ('origin_id', 'origin'):
        value = data.get(field)
        if isinstance(value, str) and value.strip():
            sample[field] = value
    return sample


def decode_raw_packet(raw_hex):
    """
    Zerlegt ein MeshCore-Raw-Paket.

    Wire Format:

        header
        [transport codes: 4 bytes]
        path_length
        path
        payload

    path_length:

        Bits 0..5 = Hop-Anzahl
        Bits 6..7 = Hashgröße - 1

    Beispiele:

        0x05 -> 5 Hops, 1 Byte pro Hop
        0x45 -> 5 Hops, 2 Byte pro Hop
        0x85 -> 5 Hops, 3 Byte pro Hop
    """

    data = bytes.fromhex(raw_hex)

    if len(data) < 2:
        raise ValueError("Paket ist zu kurz")

    header = data[0]

    route_type = header & 0x03
    payload_type = (header >> 2) & 0x0F
    payload_ver = (header >> 6) & 0x03

    offset = 1

    transport_code = None

    # TC_FLOOD und TC_DIRECT enthalten vier zusätzliche Bytes.
    if route_type in (0, 3):

        if len(data) < offset + 5:
            raise ValueError("Transport-Code oder Path-Length fehlt")

        transport_code = data[offset:offset + 4].hex()

        offset += 4

    # Kodiertes Path-Length-Byte
    path_len_raw = data[offset]
    offset += 1

    hash_size = (path_len_raw >> 6) + 1
    hop_count = path_len_raw & 0x3F

    # 4 Byte ist derzeit reserviert / ungültig.
    if hash_size > 3:
        raise ValueError(
            f"Ungültige/reservierte Path-Hash-Größe: {hash_size}"
        )

    path_byte_count = hop_count * hash_size

    if len(data) < offset + path_byte_count:
        raise ValueError(
            f"Pfad verlangt {path_byte_count} Byte, "
            f"Paket enthält aber zu wenig Daten"
        )

    path_data = data[offset:offset + path_byte_count]

    offset += path_byte_count

    hops = []

    for i in range(0, len(path_data), hash_size):
        hop = path_data[i:i + hash_size].hex()
        hops.append(hop)

    payload = data[offset:]

    return {
        "header": header,
        "route_type": route_type,
        "route_name": ROUTE_NAMES.get(
            route_type,
            f"ROUTE_{route_type}"
        ),
        "payload_type": payload_type,
        "payload_name": PAYLOAD_NAMES.get(
            payload_type,
            f"TYPE_{payload_type}"
        ),
        "payload_ver": payload_ver,
        "transport_code": transport_code,
        "path_len_raw": path_len_raw,
        "hash_size": hash_size,
        "hop_count": hop_count,
        "hops": hops,
        "payload_hex": payload.hex(),
    }


def format_path(hops):
    if not hops:
        return "direct"

    return " → ".join(
        node_label(hop)
        for hop in hops
    )


# ============================================================
# MQTT-Verarbeitung
# ============================================================

def handle_status(data):
    global last_noise_floor

    if not SHOW_STATUS:
        return

    stats = data.get("stats")
    if not isinstance(stats, dict):
        return

    noise_floor = stats.get("noise_floor")
    battery_mv = stats.get("battery_mv")
    received = stats.get("packets_received")
    queue_len = stats.get("queue_len")
    heap = stats.get("internal_heap")

    # Nicht jede identische Statusmeldung ins Terminal kippen.
    # Wir zeigen sie, wenn sich der Noise Floor verändert.
    origin_id = data.get('origin_id')
    origin_id = origin_id if isinstance(origin_id, str) and origin_id.strip() else None
    if noise_floor == last_noise_floor.get(origin_id):
        return

    last_noise_floor[origin_id] = noise_floor

    now = datetime.now().strftime("%H:%M:%S")

    print()
    print(
        f"{now}  STATUS      "
        f"Observer {data.get('origin') or origin_id or 'Unzugeordnet'} [{origin_id or 'ohne ID'}]   "
        f"NF {noise_floor} dBm   "
        f"Battery {battery_mv} mV   "
        f"RX {received}   "
        f"Queue {queue_len}   "
        f"Heap {heap}"
    )


@dataclass(frozen=True)
class Packet:
    number: int
    received_at: str
    time: str
    direction: str
    observer_hash: str | None
    group_id: str
    repeat_count: int
    first_number: int
    rssi: int | None
    snr: float | None
    length: int | None
    raw_hex: str
    decoded: dict
    path: str
    last_hop: str
    origin_id: str | None = None
    origin: str | None = None

    def to_dict(self):
        return asdict(self)


def build_packet(data):
    """Adapt Observer metadata; keep the proven wire decoder unchanged."""
    global packet_number
    raw_hex = data.get("raw")
    if not isinstance(raw_hex, str) or not raw_hex:
        raise ValueError("Packet ohne gültiges raw-Feld")
    decoded = decode_raw_packet(raw_hex)
    decoded['scope_label'] = scope_label(decoded)
    decoded["hop_labels"] = [node_label(hop) for hop in decoded["hops"]]
    if decoded["payload_type"] == 0x04:
        if decoded["payload_ver"] == 0:
            decoded.update(decode_advert(bytes.fromhex(decoded["payload_hex"])))
        else:
            decoded.update(advert=None, advert_status="Nicht unterstützte ADVERT-Version")
    if decoded["payload_type"] == 0x05 and decoded["payload_ver"] == 0:
        decoded.update(decode_group_text(bytes.fromhex(decoded["payload_hex"])))
    packet_number += 1
    observer_hash = data.get("hash")
    if not isinstance(observer_hash, str) or not observer_hash.strip() or observer_hash == "?":
        observer_hash = None
    else:
        observer_hash = observer_hash.strip().upper()
    entry = {"count": 1, "first_number": packet_number}
    if observer_hash:
        if observer_hash in seen_hashes:
            entry = seen_hashes[observer_hash]
            entry["count"] += 1
        seen_hashes[observer_hash] = entry
        seen_hashes.move_to_end(observer_hash)
        if len(seen_hashes) > MAX_SEEN_HASHES:
            seen_hashes.popitem(last=False)
    now = datetime.now().astimezone()
    return Packet(
        number=packet_number, received_at=now.isoformat(),
        time=str(data.get("time") or now.strftime("%H:%M:%S")),
        direction=str(data.get("direction", "?")).lower(),
        observer_hash=observer_hash,
        origin_id=data.get('origin_id') if isinstance(data.get('origin_id'), str) and data['origin_id'].strip() else None,
        origin=data.get('origin') if isinstance(data.get('origin'), str) and data['origin'].strip() else None,
        group_id=observer_hash or f"unhashed-{uuid.uuid4().hex}",
        repeat_count=entry["count"], first_number=entry["first_number"],
        rssi=parse_int(data.get("RSSI")), snr=parse_float(data.get("SNR")),
        length=parse_int(data.get("len")), raw_hex=raw_hex,
        decoded=decoded, path=format_path(decoded["hops"]),
        last_hop=node_label(decoded["hops"][-1]) if decoded["hops"] else "direct",
    )


def handle_packet(data, packet_sink=None):
    direction = str(data.get("direction", "?")).lower()
    if direction == "tx" and not SHOW_TX:
        return
    try:
        packet = build_packet(data)
    except (ValueError, TypeError) as exc:
        print(f"\n!!! Raw-Decode-Fehler: {exc}\nRAW: {data.get('raw')}")
        return
    print_packet(packet)
    if packet_sink is not None and packet.direction == "rx":
        packet_sink(packet)
    return packet


def print_packet(packet):
    decoded = packet.decoded
    time_text = packet.time
    packet_number = packet.number
    observer_hash = packet.observer_hash or "?"
    rssi, snr, packet_len = packet.rssi, packet.snr, packet.length
    path, last_hop = packet.path, packet.last_hop
    repeat_text = (
        f" REPEAT x{packet.repeat_count} (first #{packet.first_number})"
        if packet.repeat_count > 1 else ""
    )

    rssi_text = (
        f"{rssi} dBm"
        if rssi is not None
        else "?"
    )

    snr_text = (
        f"{snr:+.2f} dB"
        if snr is not None
        else "?"
    )

    length_text = (
        f"{packet_len} B"
        if packet_len is not None
        else "? B"
    )

    packet_name = decoded["payload_name"]
    route_name = decoded["route_name"]

    print()
    print("=" * 100)

    print(
        f"{time_text}  "
        f"#{packet_number:<5} "
        f"{packet_name:<10} "
        f"{route_name:<10} "
        f"Last Hop {last_hop:<28} "
        f"RSSI {rssi_text:<10} "
        f"SNR {snr_text}"
    )

    print(
        f"{length_text} | "
        f"Hash {observer_hash}"
        f"{repeat_text} | "
        f"{decoded['hop_count']} hops | "
        f"{path}"
    )

    print(
        f"Path hash size: {decoded['hash_size']} byte"
    )

    print(f"Scope: {scope_label(decoded)}")
    if decoded["transport_code"]:
        print(
            f"Transport code: {decoded['transport_code']}"
        )

    if decoded["payload_type"] == 0x04:
        advert = decoded.get("advert")
        if advert:
            print(f"Advert: {advert['name'] or 'Ohne Namen'} | {advert['node_type_name']}")
            print(f"Public Key: {advert['public_key']} | Timestamp: {advert['timestamp']}")
            if advert["latitude"] is not None:
                print(f"Position: {advert['latitude']:.6f}, {advert['longitude']:.6f}")
            print(f"Signatur: {advert['signature_status']}")
        if decoded.get("advert_status"):
            print(decoded["advert_status"])

    # Rohpayload nicht immer anzeigen.
    # Kann später über Detailansicht ins Web-Dashboard.
    #
    # print(f"Payload: {decoded['payload_hex']}")


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print()
        print("MeshCore OnAir MQTT")
        print("===================")
        print()
        print(
            f"Connected to MQTT broker "
            f"{BROKER_HOST}:{BROKER_PORT}"
        )
        print(f"Subscribing to {MQTT_TOPIC}")
        print()

        client.subscribe(MQTT_TOPIC)

    else:
        print(
            f"MQTT connection failed: {reason_code}"
        )


def on_disconnect(
    client,
    userdata,
    disconnect_flags,
    reason_code,
    properties
):
    print()
    print(
        f"MQTT disconnected: {reason_code}"
    )


def on_message(client, userdata, msg):
    try:
        payload_text = msg.payload.decode("utf-8")
        data = json.loads(payload_text)

    except Exception as exc:
        print()
        print(
            f"Ungültige MQTT-Nachricht auf "
            f"{msg.topic}: {exc}"
        )
        return

    if not isinstance(data, dict):
        print(f"Ungültiges MQTT-Objekt auf {msg.topic}")
        return

    if msg.topic.endswith("/status"):
        data['_mqtt_retained'] = bool(getattr(msg, 'retain', False))
        handle_status(data)
        status_sink = userdata.get("status_sink") if isinstance(userdata, dict) else None
        if status_sink is not None:
            status_sink(data)

    elif msg.topic.endswith("/packets"):
        handle_packet(data, userdata.get("packet_sink") if isinstance(userdata, dict) else None)


# ============================================================
# Start
# ============================================================

def create_client(packet_sink=None, status_sink=None):
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"meshcore-onair-{uuid.uuid4().hex[:10]}",
        userdata={"packet_sink": packet_sink, "status_sink": status_sink},
    )

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    return client


def main():
    from onair_archive import Archive
    global learned_alias
    archive = Archive()
    learned_alias = archive.resolve
    def accept_status(data):
        sample = noise_sample(data)
        if sample is not None:
            archive.accept_noise(sample)
    client = create_client(archive.accept, status_sink=accept_status)
    print(
        f"Connecting to MQTT broker "
        f"{BROKER_HOST}:{BROKER_PORT} ..."
    )

    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        client.loop_forever()

    except KeyboardInterrupt:
        print()
        print("Stopping MeshCore OnAir...")

    finally:
        try:
            client.disconnect()
        finally:
            try:
                archive.close()
            finally:
                learned_alias = None


if __name__ == "__main__":
    main()
