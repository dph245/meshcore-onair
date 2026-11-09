# Performance der Repeater-History

## Umfang und Befund

Der Repeater-Tab lädt mit `GET /api/repeaters` seine Übersicht und mit
`GET /api/repeater-history` die archivierten RSSI-Messungen je Repeater.
`packets.received` ist die lokale Empfangszeit, `packets.id` trennt einzelne
Empfänge und bestimmt die Reihenfolge bei gleichen Zeitstempeln. Der Paket-Hash
spielt für die Messpunkte keine Rolle. Der MQTT-Empfangs-SNR liegt ebenfalls im
Paketarchiv. Der Repeater-Tab zeigt bisher RSSI. Der getrennte SNR-Verlauf unter
`/api/traces` zeigt Hop-Messungen aus passiv zugeordneten TRACE-Gruppen. Die
Änderungen betreffen den Repeater-Verlauf.

Schon der Ausgangsstand `8c257bb` nutzte `packets_repeater_received` für beide
Abfragen. `COUNT(*), MIN(received), MAX(received)` prüfte im ersten Durchlauf
den RSSI aller passenden Pakete. Der zweite Durchlauf las diese Pakete erneut
und extrahierte zusätzlich Observer-ID und -Name aus JSON. Bei mehreren
Hop-Kennungen sortierte SQLite die Treffermenge. Außerdem las und gruppierte
jeder History-Aufruf die gesamte Repeater-Übersicht für die Zuordnung einer
einzelnen Kennung.

Die neue Abfrage grenzt die Auflösung auf das erste Byte der Kennung ein und
nutzt denselben Resolver wie die Übersicht. Die Primärschlüsselindizes von
`repeater_receptions` und `nodes` liefern die Kandidaten. Je Hop-Kennung läuft
ein Scan in Indexreihenfolge. Bei mehreren Kennungen führt Python die Scans
nach `(received, id)` zusammen. Bei bis zu 500 Messungen genügt dieser Scan.
Bei mehr Messungen stammt der erste Zeitpunkt aus dem Scan und der letzte
aus einem rückwärts gelesenen Indexbereich je Kennung mit `LIMIT 1`. Anzahl
und Verdichtung entstehen beim Weiterlaufen des Scans. Kennungen, Grenzen
und Messungen stammen aus derselben SQLite-Lesetransaktion.

`EXPLAIN QUERY PLAN` meldet für die Messwerte und für die Abfrage des letzten
Messwerts `SEARCH packets USING INDEX packets_repeater_received
(repeater_token=? AND received>?)`. Beim Ausgangsstand meldet der Plan für
mehrere Kennungen zusätzlich `USE TEMP B-TREE FOR ORDER BY`. SQLite wählt in
diesen Abfragen weder den reinen Zeitindex noch den Observer-Index.
Die Observer-Spalten sind seit Schema 6 beim Schreiben beziehungsweise bei der
damaligen Migration aus denselben Paketfeldern befüllt. Es gibt keine neuen
Indizes, keine zusätzliche Schreiblast und keine Migration.

## Messung am Archiv

Konsistenter lokaler Schema-15-Snapshot, 6,2 GiB, 1.963.042 Pakete, 229
Hop-Kennungen und 2.790 Nodes, geöffnet mit `mode=ro&immutable=1`. SQLite
3.46.1. Die rollenden Zeiträume endeten am jüngsten archivierten Empfang
am 6. November 2026 um 18:35:13 MEZ. Je Abfrage und ASGI-Aufruf ein
Aufwärmlauf und Median aus fünf Wiederholungen. Die API-Zeiten enthalten
Routing und JSON-Serialisierung ohne Netz- oder Proxy-Latenz.

Der dichteste Repeater (`8b558f6e…`) hatte drei Hop-Kennungen.

| Zeitraum | Messwerte / Punkte | SQL vorher → nachher | API vorher → nachher | JSON vorher → kompakt |
| --- | ---: | ---: | ---: | ---: |
| 1 Stunde | 394 / 394 | 2,7 → 1,5 ms | 9,5 → 3,2 ms | 60.077 → 10.969 B |
| 24 Stunden | 9.328 / 1.351 | 75,6 → 43,3 ms | 92,3 → 48,3 ms | 206.154 → 36.713 B |
| 7 Tage | 52.470 / 1.391 | 436,8 → 243,5 ms | 470,3 → 263,9 ms | 212.617 → 37.775 B |
| Gesamtes Archiv | 219.847 / 1.008 | 1.854,9 → 1.010,3 ms | 1.911,9 → 1.080,8 ms | 145.410 → 28.294 B |

Die SQL-Spalte summiert die separat gemessenen Schritte für Grenzen und
Messwerte. Sie enthält das Auslesen und Zusammenführen der SQLite-Cursor
ohne die Verdichtungslogik. Die API-Spalte vergleicht das bisherige Format
mit dem neuen Browser-Aufruf `compact=true`. Die Antwort ohne diese Option
behält ihr bisheriges Format. Bei einem Repeater mit nur einer Kennung
(`8b`, 144.665 Messwerte im Archiv) sank die API-Zeit für den Gesamtzeitraum
von 1.144,6 auf 627,9 ms. Ein kleinerer Repeater (`cc351265…`, 1.624
Messwerte) kam von 21,2 auf 9,8 ms.

Beim Abruf des gesamten Archivs für den dichtesten Repeater sank der
zusätzliche Prozess-RSS-Spitzenwert von 11,9 auf 4,0 MiB. Gemessen wurde
mit `ru_maxrss` vor und nach der Archivmethode, jeweils in einem frischen
Python-Prozess und als Median aus drei Läufen. Die Messung enthält SQLite
und Python bis zum Aufbau des Resultats, ohne HTTP-Serialisierung.

Im kompakten Format werden Observer-ID und damaliger Name als Paar einmal
übertragen und je Punkt referenziert. Bei bereits komprimierender
Infrastruktur fällt der Bytegewinn pro Antwort kleiner aus. Offline-gzip
für sieben Tage ergab 13.011 → 11.873 B. In drei Repeatern und je vier
Zeitfenstern waren alle 8.604 ausgegebenen Messpunkte, ihre Reihenfolge,
Observerdaten und Messwertzahlen nach dem Dekodieren identisch.

## Browser

Der Browser lädt nur Verläufe bis 160 px um den sichtbaren Bereich und hält
pro Repeater die letzten zwei geladenen Zeiträume. Neue Empfänge oder
geänderte Hop-Kennungen machen eine gespeicherte Antwort ungültig. In
rollenden Fenstern gilt sie höchstens bis zum Ablauf des ältesten enthaltenen
Punkts. Das gilt auch bei Verdichtung, weil dieser Punkt stets erhalten
bleibt. Ein Zeitraumwechsel verwirft die vorherige laufende Anfrage.
Identische Punkte behalten ihre SVG-Elemente und den Tastaturfokus.
Der Renderer verwendet denselben Zeitformatierer für alle Zeitstempel.
Drei Listener am SVG behandeln Maus, Touch und Fokus für alle Messpunkte.

Offline-Chromium mit vierfacher CPU-Drosselung. Die Startseite des
Repeater-Tabs erhielt 24 Repeater mit jeweils derselben Antwort für 24
Stunden aus dem Archivtest (1.351 Punkte). Mobil wurde zum ersten
Zeitraumwähler gescrollt. Der V8-Heap ist der Zuwachs zum Zustand vor
Taböffnung nach Garbage Collection. Die letzte Spalte misst den Median
aus neun erzwungenen Neubauten eines sichtbaren Diagramms inklusive
Layout-Abfrage, ohne Paint und Netzwerk.

| Viewport | History-Aufrufe | JSON gesamt | V8-Heap-Zuwachs | SVG-Neubau |
| --- | ---: | ---: | ---: | ---: |
| 1440 × 900 | 24 → 4 | 4.947.696 → 146.796 B | 12,7 → 1,8 MiB | 79,7 → 51,4 ms |
| 390 × 844 | 24 → 3 | 4.947.696 → 110.097 B | 14,1 → 2,0 MiB | 112,6 → 55,7 ms |

Drei Diagramme waren nach dem Einstieg im DOM. Am Desktop kam eine
vorgeladene Antwort hinzu. Die DOM-Zähler der ganzen Seite fielen von
101.178 auf rund 15.120 Knoten. Bei einer erneuten Antwort mit unveränderten
Punkten behielt die neue Ansicht das vorhandene SVG in beiden Viewports.

## Regressionstests

`python -m unittest discover -s tests -p 'test_*.py'` prüft unter anderem
identische Paket-Hashes und Zeitstempel, fehlende RSSI-Werte, Observer ohne
ID, umbenannte Observer, mehrdeutige Hop-Kennungen und die bisherige
Verdichtung gegen eine Referenz. Die Tests kontrollieren den archivierten
Empfangs-SNR je Empfang und die Dekodierung des kompakten Formats.
`python tests/browser_repeater_history.py` prüft das Laden beim Scrollen,
Wiederverwendung über Tab- und Zeitraumwechsel, Ablauf und Aktualisierung,
verspätete Antworten und die Interaktion mit den Messpunkten.

## Grenzen

Die bestehende zeitliche Verdichtung bleibt je Observer bei
erstem, letztem, niedrigstem und höchstem realen Messwert pro Abschnitt.
Eine weitere Reduktion würde Punkte entfernen, die heute sichtbar sind.
Der Erstabruf eines langen, dichten Zeitraums liest weiterhin jeden
passenden Datensatz, weil Anzahl und exakte Extrema davon abhängen.
Die SVG-Größe wächst mit der Zahl der Observer und der bereits geladenen
Diagramme. Der Browservergleich misst den Einstieg und den Neubau eines
Diagramms. Er liefert keine Produktionslastmessung oder Messung auf einem
physischen Mobilgerät.
