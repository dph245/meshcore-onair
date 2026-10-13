# Fernverbindungsanalyse – Bestandsaufnahme und Validierung

## Bestandsaufnahme

Die bisherige Nachbarschaftsauswertung berücksichtigt RX-Flood-Außenpfade und
aggregiert direkt aufeinanderfolgende Rohkennungen. `repeater_pairs` und
`repeater_paths` enthalten Empfangszähler und Zeitgrenzen, aber keine vollständigen
Zeitverteilungen oder Paketidentitäten. Diese Informationen liegen weiterhin in
`packets.received` und `packets.packet_json` vor. Ein neuer Zeitaggregatbestand ist
für die zunächst verlangte Auswertung nicht notwendig: ein partieller Pfad-/Zeitindex
ermöglicht gezielte Rohdatenabfragen. Der bestehende Index für Pakettypen hilft
beim Lesen der historischen Positions-Adverts.

Die erste Untersuchung zeigte außerdem, warum historische Positionen nötig sind:
DW1PBJ-Mobil-LKW → AEL Solar 2 erschien mit aktuellen Positionen als 507-km-Hop;
nach dem damaligen Positionsdatenstand betrug die Strecke nur etwa 100 Meter.
Aktuelle Koordinaten allein wären deshalb für diese Funktion irreführend.

## Implementierter Umfang

Ergänzung innerhalb des Nachbarn-Tabs, keine neue Hauptnavigation. Auswahl über
die vorhandene Tabelle oder die zeitlich gefilterte Fernverbindungsliste;
Entfernung/Zeitraum, Tages- und Stundenbalken, gerichtete Empfangs- und Inhaltszähler
sowie paginierte Originalpfade. Gemeinsame Zeitfenster zeigen mehrere Verbindungen,
ohne unterschiedliche Links eines Pakets als unabhängige Ereignisse auszugeben.
Die normalen Nachbarfilter und deren Cache bleiben getrennt nutzbar.

Schema 13 ergänzt einen Index, keine Tabelle, keinen Backfill von erfundenen
Zeitpunkten und keinen Worker. Der Index wird einmalig beim regulären Start gebaut.
Analyse und Cache laufen nur auf explizite Anfrage. Eine Obergrenze von 31 Tagen
und 25.000 Kandidatenempfängen begrenzt CPU und Speicher pro Anfrage. Überschreitungen
führen zu einem verständlichen Fehler, nicht zu abgeschnittenen Statistiken.

## Validierung am vorhandenen Archiv, 13.10.2026

Getestet auf einer konsistenten SQLite-Backup-Kopie in `/tmp`, Quelle ausschließlich
mit `mode=ro` und `PRAGMA query_only=ON` gelesen. Die produktive Datenbank wurde für
die Implementierungsprüfung weder migriert noch beschrieben. Die Kopie enthielt
719.772 Pakete. Die Zahlen sind lokale Messungen, keine VPS-Laufzeitgarantie.

| Messung | Ergebnis |
|---|---:|
| Einmaliger Indexaufbau / Initialisierung | 3,17 s |
| Zusätzlicher Index | 57.032.704 Bytes (54,4 MiB) |
| Erste Analyse 28.–30.09., mindestens 200 km | 0,92 s |
| Dafür gelesene Kandidaten-Rohpakete | 616 |
| Aus dem Cache geöffnete Einzelverbindung | unter 1 ms |

EXPLAIN QUERY PLAN bestätigt für Pfad-/Zeitraumabfragen
`USING INDEX packets_flood_path_received`. Der neue Index wird bei künftigen
RX-Flood-Inserts durch SQLite mitgepflegt; bestehende Nachbarabfragen nutzen ihn
nicht. Zwei Analyseergebnisse werden höchstens 120 Sekunden zwischengespeichert.

### Auersberg ↔ Wendland als Abnahmefall

A: `3134db944e652fc9e3c3da508d5ef5812db88cd0a20574dc91dd32d050495ddc`

B: `3c4afc798834a30951f527cfa1433e53a316f2dfeecbb750f2cd3787c0e0570b`

B heißt in der Datenbank „Wendland 5/2 Heidemesh“ und ist der positionsnahe
Kandidat für den genannten Torii-Tower. Entfernung: 308,497948 km.

| Richtung | Paketinhalte | Empfänge | Erster Empfang MESZ | Letzter Empfang MESZ |
|---|---:|---:|---|---|
| A → B | 8 | 26 | 28.09. 07:29:20.055292 | 29.09. 02:55:31.598102 |
| B → A | 1 | 1 | 28.09. 10:04:08.872334 | gleicher Zeitpunkt |

Gesamt: neun Paketinhalte, 27 Empfänge und 24 vollständige Pfadvarianten.
Tagesbalken A → B: 28.09. fünf, 29.09. drei, 30.09. null Pakete;
B → A: eins, null, null. Am 29.09. in Stunde 02 drei Pakete mit 16 Empfängen,
darunter das PATH-Paket um 02:55 Uhr. Diese Werte wurden gegen die vorausgehende
unabhängige Rohdatenuntersuchung geprüft. Keine Einbyte-Mehrdeutigkeiten eingerechnet.

## Tests

- `python -m unittest tests.test_distance`: benachbarte Hops, beide Richtungen,
  Schleifen, DIRECT/TX/TRACE-Ausschluss, Inhaltsidentität, Tages-/Stundenwechsel,
  exklusive Zeitgrenzen, Sommerzeit-Rückstellung, Präfixkollisionen einschließlich
  Companion/ unbekannter längerer Kennung, mobile und fehlende Positionen,
  Indexnutzung, Lastgrenze, Cache, Evidenzpagination und API-Validierung.
- `python tests/browser_distance.py`: Offline-Chromium mit HTTP-Fixtures,
  Desktop und 390-Pixel-Mobilansicht, Diagramme, Belege, Nachladen, Filterwechsel,
  Fehleranzeige und Text-Escaping. Keine produktiven Zugriffe oder MQTT-Verbindung.
- Bestehende Python- und Deno-Regressionstests ergänzen die neuen Prüfungen.

Browserprüfungen benötigen Playwright und Chromium, die Anwendung erhält keine
neue Laufzeitabhängigkeit. Testaufrufe sind vom Projektverzeichnis aus auszuführen.
