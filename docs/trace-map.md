# TRACE-Karte: Bestandsaufnahme und Umsetzung

## Datenlage

- MQTT liefert Empfänge an `build_packet`; `onair_payload.decode_payload_details`
  dekodiert TRACE (Payload-Typ 9). `Archive._write` speichert den vollständigen
  Empfang in `packets.packet_json`, einschließlich Rohdaten, Empfangszeit,
  Observer und dekodierter Payload. Altbestände werden beim Lesen nachdekodiert.
- TRACE enthält Tag, ungeprüften Auth-Code, Flags, geordnete Routen-Präfixe und
  positionsgleich zugeordnete SNR-Werte (signiertes Byte / 4). Der äußere
  TRACE-Pfad enthält **SNR, keine Geräte-Hashes**. Die Route ist zunächst eine
  angefragte Route; fehlende SNR-Werte belegen keinen erfolgreichen Durchlauf.
- Quelle und endgültiges Ziel sind nicht als sichere Geräteidentitäten enthalten.
  Ein Observer ist kein Beleg für die Quelle; erster/letzter Routen-Hop werden
  deshalb nicht als Quell-/Zielgerät ausgegeben. Die neuen Filter heißen explizit
  „Erster/Letzter Routen-Hop“ und erwarten die exakten gespeicherten Hex-Präfixe.
- Präfixe werden wie in der bestehenden TRACE-Auswertung gegen `nodes` aufgelöst.
  Kollisionen bleiben mehrdeutig. Namen stammen aus dem aktuellen Geräteverzeichnis;
  historische Namensstände werden nicht behauptet. Unbekannte Geräte bleiben erhalten.
- `nodes` enthält nur die jüngste gültige Position, `node_advert_paths` den letzten
  ADVERT-Pfad. Historische Positionen sind hingegen aus noch vorhandenen, gültig
  signierten ADVERT-Empfängen ableitbar. Die bereits vorhandene Klasse
  `onair_distance.Positions` verwendet Empfangszeit und ADVERT-Zeitstempel,
  berücksichtigt Standortwechsel und verwendet keine zukünftigen ADVERTs.
  Gelöschte Rohdaten lassen sich aus Aggregationen nicht rekonstruieren.

## Bestehende Infrastruktur und UI-Inventar

Leaflet liegt lokal unter `static/vendor`; `static/map.js` verwaltet die Karte,
Marker und Richtungspfeile. Bestehende APIs: `/api/map-nodes`,
`/api/repeater-neighbors/map`, `/table`, `/analysis`, `/api/routes`, `/api/traces`.
Die bisherige TRACE-Ansicht korreliert Empfänge in 60-Sekunden-Gruppen und bietet
SNR-Verläufe (maximal 5000 Empfänge, bis sieben Tage). Diese Funktionen bleiben erhalten.

| Aufklappbare Stelle | Entscheidung |
| --- | --- |
| Kartenhinweise | Dauerhaft sichtbarer Abschnitt; keine versteckte Kartenbedienung |
| ADVERT-Pfad im Marker-Popup | Beibehalten, örtlich begrenztes optionales Detail |
| MeshLive-Erklärung | Beibehalten, separates bestehendes Bedienkonzept |
| Nachbar-Fernanalyse und Einzelbelege | Beibehalten; keine unkontrollierte Umgestaltung |
| TRACE-SNR-, Discovery-, Repeater- und Archivkarten | Beibehalten; bestehende Auswertungen nicht ersetzen |
| Neue TRACE-Kartenbedienung | Sichtbare Modusknöpfe, Filterformular, feste Details; keine Accordions |

## Implementierung

Die vorhandene Karte bietet „Repeater / Nodes“, „Pfade“ und „TRACEs“. Der erste
Modus erhält alle bisherigen Node-Typen; Pfade verwendet die bestehende
Nachbarvisualisierung. TRACEs blendet heutige Marker/Verbindungen aus.

`GET /api/map-traces` liefert einzelne gespeicherte Empfänge. Zeitfenster sind
24 Stunden, sieben Tage, 30 Tage oder benutzerdefiniert (maximal 31 Tage),
zusätzlich erster/letzter Routen-Hop und optionale Hop-Anzahl. Der Zeitraum ist
inklusive Anfang, exklusiv Ende. Ein Empfang ist keine korrelierte Sitzung.

`GET /api/map-traces/{id}` liefert historische Hop-Positionen und SNR-Werte.
Bis zu zwei Empfänge lassen sich unabhängig von der Ergebnisseite vergleichen.
Die Details nennen Empfangszeit, unbekannte Quelle/ungesichertes Ziel, Hop-Zahl
und alle Hops einschließlich Lücken. Linien/Pfeile entstehen ausschließlich
zwischen unmittelbar benachbarten Hops mit beiden Positionen und beiden SNRs.
Keine Lücke wird übersprungen. Gleichzeitige Positions-/SNR-Beobachtungen sind
keine Garantie für heutige Erreichbarkeit oder eine vollständige Ende-zu-Ende-Route.

## Performance und Grenzen

- Keine Migration, neuen Indizes, neuen Produktionsabhängigkeiten oder Änderungen
  an historischen Daten/Aggregationen. Bestehende API-Verträge bleiben unverändert.
- SQLite-Abfrageplan auf beiden lokalen Archiven: `SEARCH packets USING INDEX
  packets_kind_id (kind=? AND id<?)`. Keyset-Pagination mit ID statt OFFSET.
- Höchstens 500 TRACE-Empfänge werden pro Anfrage geprüft (501. Zeile als
  Fortsetzungsnachweis); höchstens 50 Treffer werden übertragen. Filter laufen
  serverseitig nach dem begrenzten Index-Lesen. Stark selektive oder alte
  Zeitfenster können daher leere Seiten mit einem gültigen Weiter-Cursor erzeugen.
  Die UI kennzeichnet dies; es wird kein Vollständigkeitsanspruch für eine Seite erhoben.
- Keine TRACE-Anfragen bei Kartenbewegung oder automatischem Refresh. Liste und
  Detail-DOM sind begrenzt. Historische Positionsdaten werden unter dem vorhandenen
  Analyselock für 60 Sekunden gecacht. Im Cachezeitraum neu eingegangene ADVERTs
  können entsprechend verzögert berücksichtigt werden.
- Kalte Positionsauflösung liest die archivierten ADVERTs über den vorhandenen
  Kind-Index und sortiert sie zeitlich; sie bleibt der teuerste Schritt und skaliert
  mit der ADVERT-Menge. SQL-Progress-Handler bricht nach etwa zehn Sekunden ab
  (503 statt erfundener Positionen). Kein zusätzlicher Index ohne belegten Nutzen.
- Rein lesende lokale Messung: bei 1068 / 2704 TRACE-Empfängen erste 50 Treffer
  in 37 / 61 ms; Aufbau der Positionshistorie aus 23.663 / 66.231 ADVERTs in
  1,8 / 4,9 Sekunden; Detailauswertung danach 4 / 15 ms. Das sind lokale
  Funktionsmessungen, keine HTTP- oder VPS-Latenzgarantie.

## Validierung

Neue Python-Tests verwenden ausschließlich In-Memory-Datenbanken: historische
Standortänderung, vollständiger Empfang, unbekannter Zwischen-Hop, fehlende SNRs,
Präfixkollision, keine zukünftigen Positionen, alternative Routen, Zeit-/Hop-/
Präfixfilter, 1200 Empfänge ohne Pagination-Duplikate, begrenzte Scans,
Indexverwendung und API-Validierung.

`tests/browser_trace_map.py` prüft mit echtem Leaflet und simulierten APIs:
Pfeile/Segmente, keine Überbrückung unbekannter Hops, Vergleich, Moduswechsel,
keine Archivabfrage bei Kartenbewegung, Entfernen einer Auswahl und 390px-Mobilansicht.
Produktionsdienste/MQTT werden dabei nicht gestartet.

Testbefehle:

```sh
.venv/bin/python -m unittest discover -s tests
for test in tests/test_*ui.js; do deno run --allow-read "$test"; done
python tests/browser_trace_map.py
python tests/browser_distance.py
python tests/browser_responsive.py
```

Browser-Tests benötigen wie bisher Playwright und Chromium. Für diese Arbeit
wurden fehlende Testwerkzeuge nur unter `/tmp` installiert. Es gab keine
Bereitstellung und keinen Eingriff in laufende Dienste.

Ergebnis: 129 Python-Tests und alle 15 bestehenden JavaScript-UI-Testdateien
bestanden. Neuer TRACE-Browsertest, bestehender Fernanalyse-Browsertest sowie
Responsive-Test über neun Desktop-/Mobilformate bestanden. Die Python-Suite
meldet bestehende ResourceWarnings zu nicht geschlossenen SQLite-Verbindungen;
keine Testfehler. In der Sandbox blockierten einzelne asynchrone Tests und
Chromiums Socket-Initialisierung; außerhalb der Sandbox bestanden dieselben
Offline-Tests. `git diff --check` ohne Beanstandung.

Geänderte Dateien: `.gitignore` (neue Tests freigeben), `onair_archive.py`,
`onair_web.py`, `onair_trace_map.py`, `static/index.html`, `static/map.js`,
`static/trace-map.js`, `static/style.css`, `tests/test_trace_map.py`,
`tests/browser_trace_map.py`, `docs/trace-map.md`.

## Ergänzung: permanente SNR-Beschriftungen

Protokollprüfung am 15.10.2026 anhand der Primärquellen:
[Mesh::onRecvPacket](https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp)
fügt den Empfangs-SNR des jeweils adressierten Routen-Hops als signiertes Byte
in Viertel-dB-Schritten an. Daher gehört `snrs[i]` zu `route[i-1] → route[i]`,
nicht zum folgenden Abschnitt. Der erste Wert hat eine unbekannte sendende
Gegenstelle und erhält keine erfundene Kartenstrecke.

Der Rückweg ist in der übertragenen Routenfolge enthalten, etwa A–B–C–B–A.
Es gibt kein separates Hin-/Rückweg-Paar pro Listeneintrag. Die Firmware arbeitet
die übergebene Folge ab; aus dem TRACE allein wird kein automatischer Rückweg
oder globaler Wendepunkt behauptet. `MyMesh::onTraceRecv` ergänzt außerdem einen
letzten Empfangs-SNR im seriellen
[Companion-Ergebnis](https://github.com/meshcore-dev/MeshCore/blob/main/examples/companion_radio/MyMesh.cpp).
Dieser zusätzliche serielle Wert ist nicht Teil der archivierten Funk-Payload.
Der lokale MQTT-Observer-SNR wird nicht als Ersatz verwendet.

Decoder, Rohdaten und Karten-Detail-API erhalten beide Vorkommen eines Geräts
samt ihren unterschiedlichen Werten. `snr_min`/`snr_max` sind in der allgemeinen
TRACE-Analyse eine Messspanne; im Karten-Einzelempfang sind beide identisch.
Sie werden ausdrücklich nicht als Hin-/Rückweg interpretiert. Ein Regressionstest
prüft dies durch Decoder, Archivlesen und Detailauswertung einschließlich Altformat.
Eine rein lesende Stichprobe von 500 jüngsten archivierten TRACE-Empfängen enthielt
62 Empfänge mit bereits gemessener Gegenrichtung innerhalb derselben Routenfolge.

Die Kartenbeschriftung gruppiert dieselben eindeutig aufgelösten Endpunkte und
historischen Koordinaten **innerhalb eines Einzelempfangs**. Jede Messung bleibt in
Protokollreihenfolge erhalten, auch bei mehr als zwei Durchläufen oder gleichen
Werten. Erster Durchlauf oben, spätere Gegenrichtung darunter; →/← beziehen sich
auf die im Feld genannten Endpunkte, nicht auf die Himmelsrichtung oder eine
vermutete globale Hin-/Rückwegphase. Unbekannte Positionen, mehrdeutige Identitäten,
fehlende Werte und aggregierte Messspannen erzeugen keine Beschriftungen.

Permanente Leaflet-DivIcon-Felder zeigen TRACE-ID, Endpunkte und alle Werte.
Vorzeichen, Dezimalkomma und Viertel-dB-Präzision bleiben erhalten. Routenfarbe,
heller/dunkler Hintergrund und getrennte Felder unterscheiden Vergleichsrouten.
Die Platzierung beginnt nahe der projizierten Streckenmitte, minimiert Kollisionen
und hält sichtbare Felder innerhalb des Kartenausschnitts. Dünne Verbindungslinien
kennzeichnen Verschiebungen. Zoom, Verschieben und Größenwechsel berechnen nur
lokal neu; keine zusätzlichen API-Abfragen. Bei extrem vielen Strecken auf kleinstem
Raum kann Überlappungsfreiheit nicht garantiert werden; Messungen werden nicht versteckt.

Zusätzlich getestet: Empfänger-Zuordnung, zwei Richtungen ohne Datenverlust,
Null-/Viertel-dB-Werte, Wiederholungen, fehlende/mehrdeutige Hops, keine Umdeutung
von Min/Max, permanente Sichtbarkeit und Entfernen beim Moduswechsel. Der echte
Chromium-Test prüft zwei überlagerte Rundwege mit acht SNR-Werten sowie vier
kollisionsfreie Beschriftungsfelder auf 390px Mobilbreite, hell und dunkel.
Diese Ergänzung ändert weder Backend noch Decoder, Datenbank oder andere Kartenmodi.
