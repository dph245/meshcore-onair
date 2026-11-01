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

Eigener Tab **DX** direkt neben **Nachbarn**, ohne Akkordeon. Auswahl über
die vorhandene Nachbartabelle oder die zeitlich gefilterte Fernverbindungsliste;
Entfernung/Zeitraum, Tages- und Stundenbalken, gerichtete Empfangs- und Inhaltszähler
sowie paginierte Originalpfade. Gemeinsame Zeitfenster zeigen mehrere Verbindungen,
ohne unterschiedliche Links eines Pakets als unabhängige Ereignisse auszugeben.
Die normalen Nachbarfilter und deren Cache bleiben getrennt nutzbar.
„Analysieren“ in einer Nachbarzeile wechselt zu DX und startet die gezielte
Paaranalyse. Ein normaler Tabwechsel behält Filter/Ergebnisse bei und startet
keine neue Archivabfrage. DX ist über die bestehende Tastaturnavigation erreichbar.
Node-Schaltflächen in DX-Übersicht und Detailüberschrift öffnen die Map mit dem
entsprechenden Repeater, mindestens Zoom 12, Popup und direkten Nachbarlinks.
Die Auswahl wartet beim ersten Aufruf auf die geladenen Kartenmarker und wechselt
gegebenenfalls aus TRACE zurück zur normalen Pfadansicht. Fehlende aktuelle
Kartenpositionen werden ausdrücklich gemeldet. Die Paaranalyse bleibt separat
über „Zeitverlauf“ erreichbar; DX-Filter und Ergebnisse bleiben erhalten.

Eine feste Obergrenze von **500 km** gilt für Nachbartabelle, Kartenlinks und
Analyse. Genau 500 km bleiben enthalten. In der Nachbarübersicht zählt die
Entfernung aus den bekannten Node-Positionen; ohne eindeutige Entfernung bleibt
der Eintrag unbekannt. Die historische Analyse wendet die Obergrenze je Empfang
auf die damals vorliegenden Positionen an. Stets zu weit entfernte Kandidaten
werden bereits vor den Rohdatenabfragen ausgeschlossen. Positionsänderungen
mobiler Repeater führen nicht zum Ausschluss ihrer übrigen gültigen Empfänge.
Das Archiv und seine Rohaggregate werden dabei weder gelöscht noch verändert.

Schema 13 ergänzt einen Index, keine Tabelle, keinen Backfill von erfundenen
Zeitpunkten und keinen Worker. Der Index wird einmalig beim regulären Start gebaut.
Analyse und Cache laufen nur auf explizite Anfrage. Eine Obergrenze von 31 Tagen
und 25.000 Kandidatenempfängen in der Gesamtübersicht beziehungsweise 250.000
bei einer Einzelverbindung begrenzt CPU und Speicher pro Anfrage. Überschreitungen
führen zu einem verständlichen Fehler, nicht zu abgeschnittenen Statistiken.

### Korrektur der Einzelverbindungsanalyse, 01.11.2026

Zuvor enthielt die Anfrage des Tabellenbuttons zwar `source` und `target`, das
Backend wertete aber sämtliche passenden Verbindungen aus und filterte erst die
Antwort. Einzelverbindungen konnten dadurch am globalen Empfangslimit scheitern.
Nun werden nur Pfade mit genau dem aufgelösten benachbarten Repeaterpaar gelesen;
andere Links desselben Pfads fließen nicht in die Auswertung ein. Die vollständige
Kennungsauflösung bleibt erhalten, damit Präfixkollisionen ausgeschlossen werden.
Historische Positions-Adverts werden auf die beiden Endpunkte begrenzt.

Cache-Einträge unterscheiden Zeitraum, Mindestentfernung und kanonisches Paar;
vertauschte Endpunkte und weitere Belegseiten verwenden dasselbe Ergebnis.
Die Rohpakete werden pfadweise über den Index gelesen, statt alle
JSON-Pakete gleichzeitig zu halten. Die Einzelverbindung darf bis zu 250.000
Empfänge umfassen; die Übersicht behält ihre bisherige Grenze.

Ein Tabellenklick setzt die Mindestentfernung auf 0 km, damit auch lokale Links
wie das gemeldete 70,2-km-Paar ausgewertet werden. Filteränderungen behalten die
ausgewählte Verbindung bei; ihr Name und ihre Hashes stehen sichtbar über dem
Formular. Der Wechsel zur Gesamtübersicht verlangt eine explizite neue Analyse.
Die vorhandenen Regeln für historische Positionen und maximal 31 Tage gelten weiter.

Regressionen prüfen die Begrenzung vor Rohdatenabfragen/Limit, beide Richtungen,
andere Links desselben Pfads, getrennte Paar-Caches, lokale Verbindungen,
Lastgrenzen und Belegseiten. Der Offline-Browsertest klickt den echten
Tabellenbutton, ändert den Zeitraum und lädt Belege nach; eine gleichzeitig
absichtlich fehlschlagende Gesamtübersicht bleibt davon getrennt.

Eine zusätzliche temporäre Testdatenbank mit 57.425 unterschiedlichen Paketinhalten
auf einer einzelnen Verbindung unter 100 km wurde vollständig ausgewertet:
57.425 Empfänge und Inhalte, 25 Belege auf der letzten Seite ab Offset 57.400.
Lokale Analysezeit 0,68 s, Spitzen-RSS des gesamten Testprozesses 97,3 MiB.
Dies ist ein synthetischer Test, keine Messung am produktiven Archiv und keine
Laufzeitzusage für andere Systeme oder komplexere Pfade.

### Korrektur für viele Pfadvarianten, 01.11.2026

Der vorherige synthetische Lasttest enthielt nur einen Pfad und deckte damit
einen wichtigen Fall nicht ab: Das vorhandene Archiv enthält etwa 757.000
verschiedene Pfade; das gemeldete Paar `968d8d` ↔ `e97fce` allein mehr als 32.000
passende Pfadvarianten. Das Zusammenführen aller SQLite-Cursor öffnete für jeden
Pfad eine Abfrage gleichzeitig und wurde mit wachsender Cursorzahl immer langsamer.
Ein begrenzter Profiling-Lauf wurde nach 15 Sekunden noch beim Öffnen der Cursor
abgebrochen, bevor die eigentliche Aggregation begann.

Jetzt bleibt höchstens ein Rohpaket-Cursor aktiv. Jeder Pfad wird vollständig
verarbeitet und geschlossen, bevor der nächste gelesen wird. Zeitgrenzen werden
als Minimum/Maximum geführt; jeder Inhalt pro Richtung wird erst nach dem Lesen
aller Pfade seinem frühesten Empfang zugeordnet. Empfangsbelege werden zum Schluss
nach Empfangszeit und Paket-ID sortiert. So bleiben Diagramme, Deduplizierung und
Belegseiten unabhängig von der Pfadreihenfolge korrekt.

Die korrigierte Analyse wurde direkt mit dem gemeldeten Paar auf dem lokalen
4,8-GiB-Archiv geprüft, ausschließlich mit SQLite `mode=ro` und `query_only=ON`:
5,186 Sekunden für 55.715 Empfänge, 32.129 Pfade und 10.013 verschiedene Inhalte
im geprüften 31-Tage-Fenster. Die erste Seite enthielt 100 Belege; weitere waren
verfügbar. Der gesamte Prüfprozess erreichte 153,4 MiB Spitzen-RSS. Dies ist eine
Momentaufnahme des laufend wachsenden Archivs und keine Laufzeitzusage.

Ein zusätzlicher Regressionstest erzwingt maximal einen aktiven Cursor bei 129
Pfaden. Der früheste Empfang liegt absichtlich im zuletzt verarbeiteten Vorwärtspfad;
Tages-/Stundenzuordnung, Zeitgrenzen und die Reihenfolge über zwei Belegseiten
werden ausdrücklich geprüft.

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
