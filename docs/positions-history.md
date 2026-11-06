# Historische Positionen für DX und TRACE

Schema 16 ergänzt eine aus dem Roharchiv abgeleitete Positionshistorie.
`onair_distance.Positions` bleibt als unveränderte Legacy-Rekonstruktion erhalten.
DX und TRACE-Kartendetails nutzen dieselbe neue Positionsquelle, behalten aber ihre
unterschiedlichen Resolver und Knotentypregeln. Map, Nachbarn, MeshLive, manuelle
Positionen und Replay behalten ihre bisherigen Quellen.

## Betriebsarten

`ONAIR_POSITION_MODE` wählt `legacy` (Vorgabe), `compare` oder `normalized`.
Compose reicht diese Einstellung durch; beim direkten Python-Start muss sie im
Environment gesetzt sein. Migration und inkrementelle Pflege laufen in allen
drei Modi, nur die Lesequelle unterscheidet sich.

- `legacy`: bisherige Rekonstruktion und bisheriges Ergebnis.
- `compare`: Legacy liefert das Ergebnis. Beide Rekonstruktionen laufen auf
  demselben SQLite-Lesesnapshot mit denselben Fenstergrenzen. Verglichen werden
  Positionszustände, Bewegungsgrenzen und das vollständige fachliche Ergebnis.
- `normalized`: nur eine aktive, aktuelle `ready`-Generation mit passender
  Semantikversion, Archivkennung und Quellrevision wird verwendet.

Fehlende, veraltete oder fehlerhafte Projektionen führen zum vollständigen
Legacy-Ergebnis; Teilresultate werden nicht gemischt. Fehler und Abweichungen
werden protokolliert. Die Archive-Instanz hält danach bis zum Neustart an Legacy
fest (`position_failure`). Nach einer Vergleichsabweichung zuerst die Ursache
klären und lokal neu aufbauen; ein Neustart allein ist keine Reparatur.

DX behält seinen Ergebniscache von 120 Sekunden und zwei Ergebnissen. Ein
Cachetreffer ist kein neuer Vergleich. TRACE-Details in `compare`/`normalized`
laden die kleinen Positionsdaten je Aufruf neu; nur der Legacy-Modus behält den
bisherigen 60-Sekunden-Positionscache. Die TRACE-Gruppencaches bleiben unverändert.

## Tabellen und Zeitregeln

`position_identity` normalisiert vollständige kleingeschriebene Public Keys.
`position_state` enthält pro Generation den ersten akzeptierten Zustand und jeden
Koordinatenwechsel, mit Empfangszeit, Quellpaket-ID und auslösendem ADVERT-Zeitstempel.
Der Primärschlüssel ist `(generation,node_id,received,packet_id)`; ein zusätzlicher
Index `(generation,received,packet_id,node_id)` unterstützt Fensterabfragen.

`position_head` hält getrennt davon den höchsten akzeptierten Positions-Zeitstempel
und den zuletzt verarbeiteten Ordnungsschlüssel. Auch unveränderte Koordinaten
können diesen Zeitstempel erhöhen. `position_generation` beschreibt den
Quellstand; `position_active` enthält den aktiven Zeiger sowie Archivkennung und
Quellrevision. Ein zusätzlicher partieller Rohdatenindex auf
`(advert.public_key,received,id)` unterstützt Wiederaufbauten einzelner Schlüssel.

Backfill und Reparatur lesen nach `(received,id)`. Angenommen werden ausschließlich
ADVERTs mit SQL-NULL bei `advert_status`, gespeichertem Signaturstatus `Gültig`,
Public Key, Zeitstempel und beiden Koordinaten. Die archivierte Signaturentscheidung
wird übernommen, nicht kryptografisch neu geprüft. Es gibt keinen neuen RX-Filter.
Ein kleinerer Zeitstempel wird verworfen, ein gleicher darf ersetzen. Fehlende
Koordinaten erhöhen den Positions-Zeitstempel nicht. Es gibt keine zusätzliche
Begrenzung von Absender-Zeitstempeln gegen die lokale Empfangszeit.

`0/0` bleibt als eigener Zustand erhalten und verdrängt gegebenenfalls eine
nutzbare Position. Erst die bestehende `distance_km`-Prüfung erklärt sie für
unbrauchbar. Weder aktuelle `nodes`-Positionen noch manuelle Ersatzpositionen
füllen historische Lücken. Es wird nicht interpoliert.

Fensterabfragen laden den letzten Zustand vor `start` sowie alle Wechsel in
`[start,end)`. Gleiche Empfangszeiten werden nach Paket-ID geordnet; auch
Zwischenzustände bleiben für die bisherigen Bewegungsgrenzen erhalten. `at(t)`
liefert wie bisher den letzten Zustand mit Empfangszeit `<=t`, ohne zusätzlich
auf die ID des ausgewerteten Pakets zu begrenzen. Der interne Zeitwert eines
unveränderten Startzustands kann von Legacy abweichen; seine Position innerhalb
des Auswertefensters ist identisch.

## Migration, Writer und Wiederaufbau

Vor dem ersten Schema-16-Start eines vorhandenen Archivs erstellt `Archive`
eine zusätzliche SQLite-Sicherung neben der DB:
`<name>.pre-position-v16-<uuid>.sqlite3` (Modus 0600). Fehlschlägt die Sicherung,
beginnt diese Migration nicht. Bei einem neuen leeren Archiv entfällt die Sicherung.
Die Sicherung benötigt Platz ungefähr in Größe der bisherigen DB.

Tabellen, Indizes, Trigger, Backfill und Schema-Version werden transaktionssicher
aufgebaut. Savepoints erhalten eine umgebende Writer-Transaktion. Ein Abbruch
rollt den Aufbau zurück; Wiederholung ist möglich. Neue Generationen werden erst
nach vollständigem Aufbau aktiviert. Frühere Generationen bleiben erhalten und
werden nicht automatisch bereinigt.

Der Archiv-Writer pflegt die Projektion in derselben Transaktion wie die
Rohpakete. Die höchste verarbeitete Paket-ID verhindert doppelte Fortschreibung
beim Wiederholen der Synchronisierung. Wiederholte echte Rohrezeptionen bleiben
als eigene Pakete erhalten. Neue Meldungen mit historischer Empfangszeit bauen
den betroffenen vollständigen Schlüssel aus seinen Roh-ADVERTs neu auf, weil
veränderte Zeitstempel auch nachfolgende Annahmeentscheidungen verändern können.

Projektionsberechnungen laufen in einem Savepoint. Bei einem Berechnungsfehler
wird die unvollständige Pflege zurückgerollt und die Generation invalidiert;
der ansonsten erfolgreiche Rohpaket-Batch kann committen. Es gibt keinen neuen
Worker oder Netzwerkzugriff.

Trigger invalidieren Generationen bei Änderungen/Löschungen von ADVERTs sowie
bei explizitem Wiederverwenden alter Paket-IDs. Danach bleibt Legacy aktiv, bis
ein expliziter Wiederaufbau erfolgt. Neue externe Inserts oberhalb des
verarbeiteten ID-Stands werden als veraltete Projektion erkannt. Ein Austausch
oder eine Manipulation des Archivs unter Umgehung der Trigger erfordert ebenfalls
einen vollständigen Wiederaufbau. Änderungen von Resolverkandidaten und aktuellen
Knotentypen bleiben Aufgabe der bisherigen Auswertung.

Expliziter lokaler Neuaufbau mit zusätzlicher SQLite-Sicherung, ohne Archive-Worker
oder MQTT-Verbindung (nur den Pfad einer lokalen Kopie angeben):

```bash
.venv/bin/python -B onair_positions.py --db /absoluter/pfad/zur/lokalen-kopie.sqlite3
```

Dieses Werkzeug migriert Schema 15 nach 16 oder erstellt bei Schema 16 eine neue
Generation. Es setzt ein bestehendes OnAir-Archiv voraus, erzeugt keine leere
Ersatzdatei und sperrt konkurrierende Writer während des Aufbaus. Für die
Entwicklung eine lokale Kopie verwenden; es führt kein Deployment aus.

## Regressionen und reproduzierbarer Benchmark

```bash
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B tools/benchmark_positions.py \
  --source data/dx-advert-index-bench-20261106-183529/snapshot.sqlite3 \
  --directory data/positions-benchmark-neuer-lauf --runs 3
```

Das Benchmark-Verzeichnis muss neu sein und auf einem Datenträger mit Platz für
zwei vollständige SQLite-Kopien liegen. Die Quelle wird ausschließlich read-only
geöffnet. Das Werkzeug erzeugt eine Arbeitskopie und vor deren Migration eine
zusätzliche SQLite-Sicherung. Es prüft sämtliche Rohpaketspalten vor/nach Migration,
misst Backfill und vollständige DX-Auswertungen ohne Ergebniscache, vergleicht alle
TRACE-Details und stoppt bei einer ungeklärten Abweichung. Alle Messläufe verwenden
dieselbe migrierte DB und denselben Lesesnapshot. Warm-up erfolgt je Lesepfad;
die Reihenfolge der drei Messpaare wechselt.

Die Regressionen umfassen außerdem Zeitstempelgrenzen, gleiche Empfangszeiten,
`0/0`, fehlende Positionen, Signaturstatus, Präfixkollisionen, historische Inserts,
Neustart, Batch-Wiederholung, Writer-Fehler, abgebrochene Migration/Backfill,
Rohdatenkorrekturen und einen konkurrierenden Writer während des Vergleichs.

Die lokalen Messergebnisse vom 06.11.2026 stehen in
[positions-history-benchmark.json](positions-history-benchmark.json).
