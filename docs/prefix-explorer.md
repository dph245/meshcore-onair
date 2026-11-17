# Prefix-Explorer

Neuer Tab und `GET /api/prefix-explorer`; ausschließlich vorhandenes lokales SQLite-Archiv.
Keine neuen Netzwerkquellen, Tabellen, Migrationen oder Änderungen am Empfangspfad.

## Identität und Zeit

`nodes` enthält vom bestehenden Writer akzeptierte, gültig signierte ADVERTs.
Nur vollständige 32-Byte-Hex-Public-Keys mit aktuellem `node_type=2` zählen.
Manuelle Einträge können bekannte Repeater-Identitäten ergänzen; ihre Erstellung ist
keine Empfangsbeobachtung. Identitäten werden ohne Beachtung der Hex-Schreibweise dedupliziert.

`repeater_receptions` ergänzt letzte Sichtungen aus vorhandenen unmittelbaren
Flood-Sender-Beobachtungen. SQL gruppiert Tokens ohne Beachtung der Schreibweise;
die bestehende sortierte Prefix-Auflösung ordnet nur dann zu, wenn exakt eine
vollständige bekannte Identität passt. Die Auflösung prüft alle bekannten
Node-Typen und historischen Identitäten, nicht nur die aktiven Repeater.
Unbekannte oder mehrdeutige Tokens erzeugen weder Identitäten noch Sichtungen.

Für 7/30/60/90 Tage zählt `last_seen >= Stand - Tage*86400` und `last_seen <= Stand`;
0 steht für den gesamten Bestand. Ein gemeinsamer Cache-Stand gilt für sämtliche
Zähler, Ebenen und Listen. Kleinste eindeutige Prefixe werden in vollen Bytes
gegen alle im Zeitraum gezählten Repeater bestimmt und dürfen länger als drei
Bytes sein. Eine Kollision bedeutet mindestens zwei unterschiedliche Schlüssel.

## Datenschutz und Region

`MapVisibility` wird aus dem gesamten Identitätsbestand inklusive manueller
Einträge aufgebaut. Alte oder außerhalb des Zeitraums liegende Drei-Byte-
Kollisionspartner heben die Kartensperre nicht auf. Die API überträgt keine
Koordinaten. Gesperrte Repeater liefern keine Distanz und stehen nicht als
Bezugspunkt zur Verfügung. Namen und Schlüssel folgen der vorhandenen
Repeater-Suchverzeichnis-Konvention; statistische Belegung bleibt erhalten.

Wolfenbüttel-Zentrum (52.164, 10.540) ist eine feste Referenz, kein Standortdienst.
Alternativ lassen sich lokal bekannte, aktive und sichtbare Repeater auswählen;
das Suchfeld begrenzt die Auswahl auf höchstens 100 Treffer. OnAir besitzt hier
keine verlässliche Eigentümer-Markierung, deshalb werden diese nicht als eigene
Repeater bezeichnet. Luftlinien verwenden die vorhandene Haversine-Funktion.
25/50/100/250 km filtern nur die Liste. Unbekannte und verborgene Positionen
erscheinen bei „Alle“. Statistiken, Heatmap und Ebenenzähler bleiben global.
Die UI leitet aus räumlicher Nähe keine Funkstörung ab.

## Aufwand und Grenzen

Ein gesperrter Cache-Aufbau pro Prozess liest alle kompakten Identitäts- und
Senderaggregate in einer konsistenten SQLite-Transaktion; TTL 30 Sekunden.
Keine Paket-Scans oder JSON-Decodierung bei Benutzerinteraktionen. Kosten:
O(N log N + T log N) für N Identitäten und T Tokens; Belegungszähler O(N).
Die Detailseite liefert maximal 100 Repeater und 256 Heatmap-Zellen; nie
16.777.216 leere Kombinationen. Es wird kein zusätzlicher Index benötigt:
bestehende Primärschlüssel decken die kompakten Tabellen ab, deren Snapshot
vollständig benötigt wird. Neue Indizes auf `packets` würden hier nicht helfen.

Die Aggregate behalten jeweils die letzte Sichtung, keine typisierte
Beobachtungszeitleiste. Damit sind die angebotenen rollierenden Zeiträume
abgedeckt; beliebige vergangene Zeitfenster sind nicht implementiert. Zukünftige
falsch datierte letzte Sichtungen können ältere gültige Beobachtungen verdecken.
Die Position entspricht dem vorhandenen letzten gespeicherten Stand, nicht
zwingend dem Ort zur Beobachtungszeit. Node-Typ ist ebenfalls der zuletzt
bekannte Typ. Der Cache kann neue Daten bis zu 30 Sekunden verzögert zeigen.
Nicht unmittelbar empfangene ADVERT-Absender belegen keine direkte RF-Verbindung;
Empfangsüberschneidungen werden deshalb nicht behauptet. RF-Nachbar-Reports sind
eine getrennte, teils unvollständige Datenquelle und werden nicht als neue
Repeater-Identitäten interpretiert.

## Prüfung

- `PYTHONPATH=.:tests .venv/bin/python -m unittest test_prefix_explorer -v`
- `.venv/bin/python tests/browser_prefix_explorer.py`

Synthetische Tests prüfen Identitätsdeduplizierung, drei Kollisionslängen,
Zeitgrenzen, mehrdeutige/unvollständige Tokens, Positionen, Luftlinien,
zeitscheibenunabhängige Kartensperren, Pagination und einen 12.000-Identitäten-
Bestand ohne Paketabfragen. Chromium nutzt echte Explorer-Abfragen gegen eine
synthetische SQLite-Datei, abgefangene HTTP/WebSocket-Verbindungen, Desktop,
320/390-Pixel-Mobilansichten, Querformat, Themes und den bestehenden Live-Tab.
Keine Produktionsdatenmessung, kein MQTT-Zugriff oder Neustart.

Abschlussprüfung dieses Sprints: 227 Python-Tests und 18 bestehende JavaScript-
UI-Tests erfolgreich; Explorer-Browsertest in vier Viewports erfolgreich.
Eine lokale synthetische Stichprobe mit 12.000 Identitäten und 12.000 Vollschlüssel-
Empfangstokens benötigte für `prefix=77` einschließlich Cache-Aufbau etwa 143 ms;
die JSON-Antwort mit 100 Einträgen hatte rund 36 KB. Dies ist eine einzelne
Testmessung auf dem Entwicklungsrechner, keine Produktions- oder Lastgarantie.

API-Parameter: `days=0|7|30|60|90`, `prefix` leer oder 2/4/6 Hex-Zeichen,
`reference` als vollständiger sichtbarer Repeater-Schlüssel (leer: Wolfenbüttel),
`reference_q` zur Suche im Bezugsverzeichnis, `radius=0|25|50|100|250`,
`sort=prefix|count|distance`, `offset` für Seiten zu 100 Einträgen.
