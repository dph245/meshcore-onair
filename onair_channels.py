"""Decode group text using locally configured MeshCore channel secrets."""
import base64
import hashlib
import hmac
import json
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


CONFIG_PATH = Path(__file__).with_name("channels.json")
PUBLIC_KEY = bytes.fromhex("8b3387e9c5cdea6ac9e5edbaa115cd72")


def load_channels(path=CONFIG_PATH):
    """Accept hex/base64 secrets, or derive hashtag keys from their names."""
    channels = {"Public": PUBLIC_KEY}
    if not path.exists():
        return channels
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("channels.json muss Kanalnamen auf Schlüssel abbilden")
    for name, value in config.items():
        if not name or not isinstance(value, (str, type(None))):
            raise ValueError("Ungültiger Kanaleintrag in channels.json")
        if value is None and name.startswith("#"):
            key = hashlib.sha256(name.encode("utf-8")).digest()[:16]
        elif isinstance(value, str):
            try:
                key = bytes.fromhex(value)
            except ValueError:
                try:
                    key = base64.b64decode(value, validate=True)
                except ValueError:
                    raise ValueError(f"Ungültiger Schlüssel für Kanal {name}") from None
        else:
            raise ValueError(f"Schlüssel fehlt für Kanal {name}")
        if len(key) not in (16, 32):
            raise ValueError(f"Schlüssel für Kanal {name} muss 16 oder 32 Byte haben")
        channels[name] = key
    return channels


CHANNELS = load_channels()


def decode_group_text(payload, channels=None):
    # Wire format and crypto: meshcore-dev/MeshCore docs/payloads.md,
    # src/Utils.cpp and src/helpers/BaseChatMesh.cpp.
    result = {"group_text": None, "group_channel": None,
              "group_text_status": "Nicht entschlüsselbar"}
    if len(payload) < 19 or (len(payload) - 3) % 16:
        result["group_text_status"] = "Ungültige Text-Payload"
        return result
    ciphertext = payload[3:]
    for name, key in (CHANNELS if channels is None else channels).items():
        if hashlib.sha256(key).digest()[0] != payload[0]:
            continue
        mac = hmac.digest(key.ljust(32, b"\0"), ciphertext, "sha256")[:2]
        if not hmac.compare_digest(mac, payload[1:3]):
            continue
        decryptor = Cipher(algorithms.AES(key[:16]), modes.ECB()).decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        if plaintext[4] >> 2 != 0:
            result["group_text_status"] = "Nicht unterstütztes Textformat"
            return result
        try:
            message = plaintext[5:].split(b"\0", 1)[0].decode("utf-8")
        except UnicodeDecodeError:
            result["group_text_status"] = "Ungültiger Nachrichtentext"
            return result
        return {"group_text": message, "group_channel": name,
                "group_text_status": None}
    return result
