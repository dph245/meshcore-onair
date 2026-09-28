import json
import tempfile
import unittest
from pathlib import Path

from onair_archive import Archive
from onair_mqtt import build_packet, format_packet
from onair_payload import decode_payload_details


def packet(kind, payload, version=0):
    return build_packet({'raw': bytes([version << 6 | kind << 2 | 1, 0]).hex() + payload.hex()})


def fields(decoded):
    return {f['label']: f['value'] for f in decoded['payload_fields']}


class PayloadTests(unittest.TestCase):
    def test_control_discovery_requests(self):
        for flags in (0x80, 0x81):
            for suffix in (b'', bytes(4), bytes.fromhex('01000000')):
                p = packet(11, bytes([flags, 0x94]) + bytes.fromhex('12345678') + suffix)
                f = fields(p.decoded)
                self.assertIsNone(p.decoded['payload_status'])
                self.assertEqual(f['Discovery-Tag (uint32, Little Endian)'], '0x78563412')
                self.assertEqual(f['Gesuchte Node-Typen'], 'Repeater, Sensor, Typ 7 (0x94)')
                self.assertEqual(f['Angeforderter Public Key'],
                                 '8-Byte-Präfix' if flags & 1 else 'Vollständig (32 Byte)')
                self.assertEqual(f['Geändert seit (UTC)'], '1970-01-01T00:00:01+00:00'
                                 if suffix == bytes.fromhex('01000000') else 'Keine Zeitbegrenzung (0)')
                self.assertIn('DISCOVER_REQ', format_packet(p))

    def test_control_discovery_responses(self):
        for size in (8, 32):
            for raw_snr, snr in ((0xf5, '-2.75'), (0x19, '6.25'), (0x80, '-32')):
                p = packet(11, bytes([0x92, raw_snr]) + bytes.fromhex('12345678') + bytes(range(size)))
                f = fields(p.decoded)
                self.assertIsNone(p.decoded['payload_status'])
                self.assertEqual(f['Node-Typ'], 'Repeater (2)')
                self.assertEqual(f['SNR der Suchanfrage beim antwortenden Node'], f'{snr} dB')
                self.assertEqual(f['Public-Key-Präfix (8 Byte)' if size == 8 else 'Public Key (32 Byte)'],
                                 bytes(range(size)).hex())
                self.assertIn('DISCOVER_RESP', format_packet(p))

    def test_control_malformed_and_unknown(self):
        for raw in [b''] + [bytes([0x80]) + bytes(n) for n in (0, 1, 2, 3, 4, 6, 7, 8)] + [
                bytes([0x92]) + bytes(n) for n in range(39) if n not in (13, 37)]:
            with self.subTest(raw=raw.hex()):
                d = packet(11, raw).decoded
                self.assertTrue(d['payload_status'])
                self.assertEqual(fields(d)['CONTROL-Nutzdaten (Hex)'], raw.hex())
                json.dumps(d, allow_nan=False)
        d = packet(11, bytes.fromhex('70aabb')).decoded
        self.assertIn('Unbekannter', d['payload_status'])
        self.assertEqual(fields(d)['CONTROL-Untertyp'], '0x7')
        self.assertIn('Version', packet(11, bytes(10), version=1).decoded['payload_status'])

    def test_ack_and_multipart_byte_order_and_extensions(self):
        for kind, prefix in ((3, b''), (10, b'\x23')):
            p = packet(kind, prefix + bytes.fromhex('12345678abcd'))
            f = fields(p.decoded)
            self.assertEqual(f['ACK-Hash (Wire-Reihenfolge)'], '12345678')
            self.assertEqual(f['ACK-Wert (uint32, Little Endian)'], '0x78563412')
            self.assertEqual(f['Weitere ACK-Daten (Hex)'], 'abcd')
            self.assertIsNone(p.decoded['payload_status'])
            self.assertIn('ACK 12345678', format_packet(p))
            if kind == 10:
                self.assertEqual(f['Weitere Pakete'], '2')

    def test_encrypted_envelopes_do_not_claim_plaintext(self):
        for kind in (0, 1, 2, 7, 8):
            source = bytes(range(32)) if kind == 7 else b'\xbb'
            p = packet(kind, b'\xaa' + source + b'\x12\x34' + bytes(16))
            d, f = p.decoded, fields(p.decoded)
            self.assertEqual(f['Ziel-Hash (1 Byte)'], 'aa')
            self.assertEqual(f['MAC (ungeprüft)'], '1234')
            self.assertEqual(f['Chiffretext (Hex)'], '00' * 16)
            self.assertEqual(f['Absender-Public-Key' if kind == 7 else 'Absender-Hash (1 Byte)'], source.hex())
            self.assertIn('verschlüsselt', d['payload_status'])
            self.assertIn('Channel-Schlüssel', format_packet(p))
            self.assertNotIn('request_type', d)
            if kind == 8:
                self.assertIn('zurückgemeldete Pfad', f['Pfad-Bedeutung'])

    def test_truncation_versions_and_unknown_subtypes(self):
        for kind, minimum in ((0, 20), (1, 20), (2, 20), (3, 4), (7, 51), (8, 20), (10, 5)):
            for size in range(minimum):
                with self.subTest(kind=kind, size=size):
                    d = packet(kind, (b'\x03' + bytes(60))[:size]).decoded
                    self.assertTrue(d['payload_status'])
                    json.dumps(d, allow_nan=False)
            d = packet(kind, bytes(64), version=1).decoded
            self.assertIn('Version', d['payload_status'])
            self.assertEqual(d['payload_fields'], [])
        d = packet(10, bytes.fromhex('21aabbccdd')).decoded
        self.assertNotIn('ACK-Hash (Wire-Reihenfolge)', fields(d))
        self.assertIn('Untertyp', d['payload_status'])
        self.assertEqual(decode_payload_details({'payload_type': 5}), {})
        self.assertIn('Hex', decode_payload_details({'payload_type': 3, 'payload_hex': 'zz'})['payload_status'])

    def test_old_archive_is_enriched_without_rewriting(self):
        for kind, raw, summary in ((3, '12345678', 'ACK 12345678'),
                                   (11, '800412345678', 'DISCOVER_REQ')):
            with self.subTest(kind=kind):
                self.check_archive_enrichment(kind, raw, summary)

    def check_archive_enrichment(self, kind, raw, summary):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder) / 'test.sqlite3')
            try:
                p = packet(kind, bytes.fromhex(raw)).to_dict()
                for key in ('payload_summary', 'payload_fields', 'payload_status'):
                    del p['decoded'][key]
                with archive.connect() as db:
                    archive._write(db, [p])
                d = archive.search()['items'][0]['packet']['decoded']
                self.assertIn(summary, d['payload_summary'])
                with archive.connect() as db:
                    stored = json.loads(db.execute('SELECT packet_json FROM packets').fetchone()[0])
                self.assertNotIn('payload_summary', stored['decoded'])
            finally:
                archive.close()
