# Historische TRACE-Linkstrecken

Die TRACE-Ansicht startet mit der Linkübersicht. Im selben Leaflet-Container
bleibt der Vergleich einzelner Empfänge unter „Messgruppen & Karte“
verfügbar. Die Chronik mit Routenverlauf behält ihren bisherigen,
zeitlich begrenzten Datenpfad. Die Linkübersicht arbeitet auf der
vollständigen TRACE-Projektion des Archivs.

Die Übersicht unterstützt 24 Stunden, 7 und 30 Tage, den gesamten
Bestand und einen festen Von-/Bis-Zeitraum. „Unbekannt“ filtert
Messwerte mit unbekanntem, widersprüchlichem oder zeitlich unsicherem
Observer-Profil. SF7 und SF8 sind direkt wählbar. Weitere SF erscheinen,
sobald sie im geladenen Zeitraum vorkommen. Der Median ist voreingestellt.
Letzter Wert, Minimum und Maximum lassen sich lokal umschalten.

Jede geografisch belegte Verbindung hat ein Canvas-Objekt. Zwei
Repeater mit derselben belegten Position erscheinen als Punkt.
Beschriftungen werden ab Zoom 9 im Kartenausschnitt eingeblendet.
Pfeile beziehen sich auf die Reihenfolge der im Feld genannten
Endpunkte. Für jede Profilkombination zeigt die Detailansicht beide
Richtungen und kennzeichnet fehlende Gegenmessungen. Messwerte mit
eindeutig identifizierten Endpunkten zählen auch dann in die
Linkstatistik, wenn zu ihrem Zeitpunkt keine sichere Geometrie vorliegt.
Die sichtbare Geometrie stammt vom jüngsten kartierbaren Messwert
innerhalb des gewählten Filters. Die Übersicht nennt teilweise
beobachtete Messungen, Empfänge ohne Dekodierung und unkartierbare
Messwerte mit Grund.

Die Karte behält ihre Filter und Layer bei archivbedingten
Aktualisierungen. Snapshots enthalten die TRACE-Revision vollständig.
Der WebSocket sendet die Revision nach Änderungen an der Projektion,
an relevanten Archivdaten oder beim Backfill. Die aktive Karte bündelt
solche Hinweise auf höchstens eine Hintergrundabfrage pro zehn
Sekunden. Beim Verlassen der Ansicht werden laufende Anfragen
abgebrochen und Canvas und Zoom-Beschriftungen ausgehängt. Die
Layerobjekte bleiben zum Wiederverwenden im Speicher.

## Paketformat und Zuordnung der Richtung

MeshCore legt nach dem äußeren Header den SNR-Fortschritt ab. Jedes
Byte entspricht einem signierten Viertel-dB-Wert. Die Payload beginnt
mit je vier Bytes Tag und Auth-Code in Little Endian, gefolgt von
einem Flag-Byte und der vollständigen angefragten Route. Die unteren
zwei Bits der Flags kodieren die Breite als 1, 2, 4 oder 8 Bytes.
Die beobachteten 8-Byte-Frames verarbeitet dieselbe Logik. Reservierte
Flags und andere nicht interpretierbare Frames bleiben über Rohpaket
und Empfangsstatus im Archiv. Der allgemeine Path-Hash im äußeren
Header und die TRACE-Präfixbreite sind unterschiedliche Felder.
[MeshCore-Paketformat](https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md)

`snrs[i]` gehört zum Empfänger `route[i]`. Ab `i = 1` ist die
unmittelbar vorherige Adresse `route[i-1]` die gemessene Gegenstelle.
Der Wert bei `i = 0` bleibt am ersten Hop erhalten. Das Funkpaket
weist die Identität des auslösenden Companion und dessen Standort
nicht verlässlich aus. Der serielle Companion-Endwert liegt außerhalb
des beobachteten TRACE-Pakets. Der Observer-RSSI und Observer-SNR
gehören ausschließlich zum jeweiligen MQTT-Empfang.
[Mesh::onRecvPacket und Mesh::sendDirect](https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp)
[MyMesh::onTraceRecv](https://github.com/meshcore-dev/MeshCore/blob/main/examples/companion_radio/MyMesh.cpp)

Der auf dem Funkweg beobachtete Rückweg steckt in der Routenfolge.
Die Projektion erhält jede Position einschließlich wiederholter
Repeater und jedes gemessene Auftreten eines gerichteten Paars.
Asymmetrische und unvollständige Routen folgen derselben Regel.
„Vollständig“ bedeutet, dass für alle adressierten Hops ein
transportierter SNR vorliegt. An einem fehlenden oder mehrdeutigen
Hop endet die Geometrie. Nachfolgende belegte Nachbarhops können
eine eigene Strecke bilden.

## Schema 18 und Korrelation

- `trace_measurement` speichert eine stabile interne ID, die
  unveränderte Wire-Identität, Präfixbreite, Route, längsten konsistenten
  SNR-Fortschritt und erste und letzte Ereigniszeit. Die ID ist die
  Paket-ID der zuerst indexierten Beobachtung dieser Gruppe.
- `trace_observation` verweist für jeden archivierten TRACE-Empfang
  auf das Rohpaket. Sie hält Observer-ID, Quellzeit, OnAir-Empfangszeit,
  Ereigniszeit, SNR-Abdeckung, Retain-Kennzeichen, Korrelationsgrund
  und die Referenz eines erkannten Duplikats. Die beim Indexieren
  ermittelte Profilqualität und der Schema-17-Zeitschlüssel bleiben
  am Empfang erhalten. Das Profil selbst steht in der vorhandenen
  Historie. Unlesbare Einträge haben eine Rohpaket-ID und keinen
  Messungsbezug.
- `trace_sample` enthält je Messung und empfangendem Hop ein Paar
  vollständiger beobachteter Präfixe, den signierten Viertel-dB-Wert
  und die früheste Zeit der zugehörigen Beobachtung. Indizes decken
  Zeitfenster und gerichtete Präfixpaare ab. Funkprofilzeitreihen
  werden gesammelt über die Schema-17-Indizes für die beteiligten
  Observer gelesen. Median und weitere Statistiken entstehen
  serverseitig aus diskreten Viertel-dB-Histogrammen.
- `trace_backfill` hält Obergrenze, Cursor, Zahl gelesener TRACE-Zeilen
  und Abschlussstatus. Der Archivschreiber nutzt `packets_kind_id`
  und führt höchstens 100 Altzeilen je Transaktion nach. Live-Empfänge
  haben Vorrang. Projektion und Cursor werden gemeinsam übernommen.
  Bei Neustart setzt die Verarbeitung am persistierten Cursor an.
  Die Paket-ID macht Wiederholungen idempotent. Der Backfill liest die
  archivierten Rohpakete und schreibt die Projektion.

Wire-Identität umfasst Routingtyp, Version, die rohen Transportcodes
sowie Tag, Auth-Code, Flags und Route. Eine Gruppe umfasst maximal
60 Sekunden. Korrelation verlangt einen identischen gemeinsamen
SNR-Präfix. Beobachtungen verschiedener Observer desselben Fortschritts
müssen innerhalb von drei Sekunden liegen. Verschiedene Fortschritte
können korrelieren, solange bekannte Zeitreihen desselben Observers
und die vorhandene Abdeckung dazu passen. Zeitumkehrungen in der
nachrichtenbasierten Reihenfolge werden mit plausibler Quellzeit
aufgelöst. Ein neues Vorkommen desselben Fortschritts beim selben
Observer bleibt separat. Ein gleiches hochauflösendes Zeitmerkmal
beim selben Observer und derselbe Fortschritt mit unveränderten
SNR-Bytes kennzeichnen eine Wiederzustellung. Der Rohbeleg bleibt auch
in diesem Fall referenziert. Abweichende SNR-Bytes und mehrere
plausible Gruppen erzeugen separate, entsprechend gekennzeichnete
Messungen. Ein identischer Wiederholungsversuch, den ausschließlich
verschiedene Observer im Korrelationsfenster mit identischen SNR-Daten
beobachten, lässt sich passiv nicht immer trennen.

Die Ereigniszeit ist die plausible Observer-Quellzeit, ersatzweise
der OnAir-Empfang. Alte Paketzeilen enthalten gewöhnlich nur eine
Uhrzeitanzeige ohne belastbare Datumsangabe. Retained Empfänge ohne
Quellzeit bleiben in einer eigenen Gruppe mit unbekanntem Profil.
Fehlen in Live-Paketen vollständige IDs, kann das übliche MQTT-Topic
mit Public Key die Identität belegen. Ein Widerspruch zwischen Topic
und Payload lässt die Observer-ID für diese Zuordnung offen.

Präfixauflösung erfolgt bei der Abfrage gegen bekannte vollständige
Identitäten. Kürzere Präfixe behalten ihre Länge. Eindeutige
Vier-Byte-Präfixe können eine Kollision der ersten drei Bytes umgehen.
Mehrdeutige, unbekannte und nicht geografisch zuordenbare Hops bleiben
mit Status auswertbar. Signierte ADVERTs können die Identität
nachträglich auflösen. Positionen stammen aus der zeitlich passenden
Schema-16-Historie. Widersprüchliche Koordinaten für denselben
signierten Key und dieselbe ADVERT-Quellzeit sperren seine Geometrie.
Die Prüfung verwendet den vorhandenen ADVERT-Index für beteiligte
Repeater, deren Position sich im Archiv geändert hat.

## Funkprofile und Grenzen der Beobachtung

Das Schema-17-Profil wird je Observer und Ereigniszeit nach denselben
Regeln wie `Archive.observer_radio_at` eingeordnet. Zusätzlich zur
Einstufung beim Indexieren wertet die Abfrage die Profilhistorie
erneut aus. Damit wirken später bekannt gewordene Übergänge und
Konflikte auf die Auswertung. Für jeden gerichteten Wert zählen
ausschließlich Beobachtungen, die ihn tatsächlich transportieren.
Bekannte, widerspruchsfreie Werte können ein eindeutiges Profil
liefern. Dazu muss eine tatsächliche Profilmeldung alle verwendeten
Parameter enthalten. Konkurrierende Profile, erkannte Übergänge
und fehlende SF-Evidenz bleiben unter „Unbekannt“. Frequenz, Bandbreite,
SF, CR und vorhandene weitere Funkparameter bleiben getrennt
gruppierbar. „Bestätigt“ bezeichnet eine gemeldete
Observer-Konfiguration zu ihrem Quellenzeitpunkt. „Zuletzt gemeldet“
bezeichnet den letzten verfügbaren Beobachtungsstand.
[Schema-17-Zeitsemantik](observer-radio.md#schema-17-und-zeitliche-zuordnung)

Die Profilzuordnung beschreibt die Einstellungen der empfangenden
Observer. Die Konfiguration einzelner Sender am TRACE-Pfad und die
Coding Rate auf dem Funkweg bleiben offen. Ausbleibende Beobachtungen
lassen den tatsächlichen Funkverlauf offen. Der Vergleich von SF7
und SF8 und die Auswertung einer Messkampagne folgen separat.

`GET /api/trace-links` liefert je Zeitraum und SF aggregierte
Verbindungen. `start` ist einschließlich, `end` ausschließlich.
Zwei sortierte vollständige Public Keys als `a` und `b` laden
seitenweise bis zu 50 Einzelwerte einer Verbindung. Die
Einzelwerte zeigen Richtung, Profilgüte und Rohpaket-Referenzen.
`GET /api/trace-measurements/{id}` liefert die geordnete Route,
alle Empfangsbelege, RSSI und SNR je Observer und die Zuordnungsgründe.

## Realer 4-Byte-TRACE

Archivpaket **#2604758**, Projektion **#2604741**. Header `26 07`
steht für DIRECT-TRACE mit sieben SNR-Bytes. Der Fortschritt lautet
`2c 31 1e 29 29 25 31`. In der Payload folgen
`82 56 cb a8 50 8b df 26 02` mit Tag `a8cb5682`, Auth-Code
`26df8b50` und Flag `02` für 4-Byte-Präfixe.

| Gemessene Richtung | SNR-Byte | dB |
| --- | --- | ---: |
| unbekannte Quelle → `77730034` | `2c` | +11,00 |
| `77730034` → `747400e7` | `31` | +12,25 |
| `747400e7` → `6f33a924` | `1e` | +7,50 |
| `6f33a924` → `bf92b989` | `29` | +10,25 |
| `bf92b989` → `6f33a924` | `29` | +10,25 |
| `6f33a924` → `747400e7` | `25` | +9,25 |
| `747400e7` → `77730034` | `31` | +12,25 |

Vier verschiedene vollständige Keys wurden aufgelöst. Für
`77730034` und `bf92b989` widersprechen sich archivierte
Standortbelege. Die Karte zeichnet aus dieser Messung
`747400e7` ↔ `6f33a924`. Alle sechs gerichteten Werte
und der erste Empfangswert bleiben in der Projektion.

## Abnahme auf dem lokalen Archiv

Am 26.11.2026 umfasste der Benchmark 2.643.737 Paketzeilen in
Schema 17 und 8.126 TRACE-Empfänge. Das Quellarchiv war lesend
eingebunden. Die Schema-18-Projektion lag in einer separaten
temporären SQLite-Datei. Mit der üblichen 100-ms-Wartezeit bei
leerer Live-Warteschlange dauerte die Aufarbeitung 8,68 s. Das
Abarbeiten der Batches benötigte davon 0,47 s. Der längste
Batch inklusive Projektion und Commit dauerte 10,44 ms. Die
zusätzliche SQLite-Datei belegte nach dem Checkpoint 2.056.192
Bytes (1,96 MiB). Sechs TRACE-markierte Empfänge hatten ein
nicht auswertbares Format und blieben mit Rohreferenz erhalten.

SQL-Werte sind Median aus fünf Abfragen der gerichteten Werte
mit Zeitfilter einschließlich SQLite-Auslesen, ohne Aggregation.
„Gesamt“ pro Zeile umfasst zusätzlich Positionsabgleich,
Observer-Historie und Aggregation im Servercode. JSON-Größen
gelten unkomprimiert ohne HTTP-Header.

| Zeitraum | SQL | Gesamt | JSON | TRACE-Messungen | Werte auf Karte | Linkobjekte |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 24 Stunden | 0,18 ms | 39,48 ms | 1.150 B | 71 | 21 | 1 |
| 7 Tage | 0,17 ms | 36,13 ms | 1.150 B | 71 | 21 | 1 |
| 30 Tage | 0,39 ms | 57,32 ms | 20.870 B | 747 | 163 | 28 |
| gesamter Bestand | 1,80 ms | 93,29 ms | 82.505 B | 3.177 | 1.042 | 106 |

Im gesamten Archivfenster hatten 2.645 Messungen keine kartierbare
Strecke. Die vorhandene Profilhistorie erlaubte für die sichtbaren
Archivmessungen keine belastbare SF-Zuordnung. SF7/SF8 und weitere
Profile wurden deshalb mit gezielten Tests geprüft. Eine bedarfsgeladene
Einzelwertseite der ersten Verbindung im Gesamtfenster benötigte
22,39 ms und 15.528 Bytes JSON.

Chromium lief offline mit den realen Aggregaten des Gesamtzeitraums
bei 1280 × 900 px und lokalen Testkacheln. Vom dekodierten JSON bis
zum zweiten Animationsframe vergingen 29,50 ms. Der Klick bis zur
bestätigten Darstellung inklusive Testinstrumentierung dauerte
87,48 ms. CDP maß den Hauptthread und JS-Heap nach Garbage Collection
in 2,5-s-Fenstern ohne neue MQTT-Meldungen. Der Renderer-PSS ist
die Summe der anteilig zugerechneten Speicherseiten der drei
Chromium-Rendererprozesse der Testsitzung aus `/proc`.

| Zustand | CPU des Hauptthreads | JS-Heap | Renderer-PSS | DOM-Knoten |
| --- | ---: | ---: | ---: | ---: |
| inaktiv vor erstem Anzeigen | 0,148 % | 1,39 MiB | 135,37 MiB | 1.804 |
| aktiv | 0,580 % | 3,34 MiB | 160,37 MiB | 2.507 |
| inaktiv nach Anzeigen | 0,035 % | 3,36 MiB | 148,09 MiB | 2.512 |

Der Heap nach einem Tabwechsel enthält die wiederverwendete Karte,
Filter, Layer und Aggregate. Die CPU-Zahlen sind lokale Stichproben
einschließlich des üblichen UI-Hintergrundaufwands. Tile-Netzwerk
und Belastung durch den produktiven MQTT-Strom lagen außerhalb
der Messung.

```bash
PYTHONPATH=. .venv/bin/python tools/benchmark_trace_history.py data/onair.sqlite3 \
  --fixture-dir /tmp/onair-trace-benchmark --sample-id 2604758
.venv/bin/python -m unittest discover -s tests -v
for test in tests/test_*ui.js; do deno run --allow-read=static "$test" || exit; done
.venv/bin/python tests/browser_trace_links.py --benchmark /tmp/onair-trace-benchmark
.venv/bin/python tests/browser_trace_map.py
.venv/bin/python tests/browser_map_visibility.py
.venv/bin/python tests/browser_responsive.py
```

252 Python-Tests und 18 Deno-Skripte bestanden. Chromium prüfte helles
und dunkles Theme, Zoom-Beschriftungen, Canvas und Layer-Wiederverwendung,
Funkprofil- und Zeitfilter, WebSocket-Aktualisierung, Lazy Loading,
Messgruppenvergleich, Kartenkollisionen sowie die responsiven Ansichten.
