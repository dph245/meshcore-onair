# Repeater mit kollidierenden 3-Byte-Präfixen

## Geprüfte Identitätssemantik

`onair_advert.decode_advert()` liest die ersten 32 Payload-Bytes als vollständigen
Public Key und gibt sie mit `hex()` aus. `Archive._record_node()` übernimmt nur
dekodierbare, gültig signierte ADVERTs in `nodes`; der vollständige `public_key`
ist dort der Primärschlüssel. Wiederholte Empfänge aktualisieren dieselbe Zeile.
Die vorhandenen Resolver (`onair_prefixes`, `onair_neighbors`, `onair_trace`)
ordnen kurze Pfadkennungen durch Public-Key-Präfixvergleich zu.

Das hier verwendete 3-Byte-Präfix ist deshalb `public_key[:6].lower()`.
Es wird kein zusätzlicher SHA-Hash berechnet. `observer_hash` bezeichnet dagegen
den Paket-Hash und spielt für diese Filterung keine Rolle. Kurze, nicht eindeutig
aufgelöste Pfadkennungen sind keine zusätzlichen Repeater-Identitäten.

## Gemeinsame Kartenregel

`onair_map_visibility.MapVisibility` betrachtet alle bekannten vollständigen
Repeater-Keys (`node_type == 2`), unabhängig von Alter, letzter Position oder
Kartenausschnitt. Schreibweisen desselben Keys zählen nur einmal. Mindestens zwei
verschiedene Keys mit denselben ersten sechs Hex-Zeichen sperren diesen Präfix.
Chat, Room-Server und Sensoren tragen nicht zur Repeater-Kollision bei und werden
selbst bei gleichem Präfix nicht ausgeblendet.

Manuelle Repeater-Referenzidentitäten zählen ebenfalls; ein bekannter anderer
Node-Typ wird durch einen manuellen Eintrag nicht zum Repeater. Manuelle
Koordinaten werden dadurch weiterhin nicht in das Replay übernommen.

Die Regel wirkt an folgenden Stellen:

- Hauptkarte: `Archive.map_nodes()` entfernt aktuelle und historische kollidierende
  Repeater aus `items`. Die Suchliste behält die Identitäten mit dem Hinweis
  „Hash-Präfix-Kollision: Standort ausgeblendet“. Fehlende Marker erzeugen auch
  keine Verbindungen, Positionsversatzlinien oder auswählbaren Standorte.
- MeshLive und Replay: Bootstrap-Antworten enthalten `map_repeater_keys`, auch für
  alte und positionslose Repeater. Im Replay wird diese Liste ermittelt, bevor
  unsichere historische Node-Daten zurückgesetzt werden. Der aktuelle Schutz gilt
  damit auch vor dem Abspielen des zweiten ADVERTs.
- TRACE: `onair_trace_map.detail()` unterdrückt historische Hop-Positionen nach
  derselben Regel, auch bei wiederverwendeter Positionshistorie und in den Modi
  `legacy`, `compare` und `normalized`. Hops, SNR und Empfangsdaten bleiben erhalten.
- DX besitzt keine eigene Karte, sondern öffnet die Hauptkarte. Weitere eigene
  Leaflet-Karten wurden in `static/` nicht gefunden.

`static/map-visibility.js` ist die gemeinsame Browser-Regel für alle Karten.
HTTP-Antworten liefern die bekannten Repeater-Keys; gültige ADVERTs aus bestehenden
WebSocket-Snapshots und -Deltas ergänzen sie inkrementell. Eine neue Kollision
entfernt vorhandene Marker, Linien, offene Kartenpopups und MeshLive-Animationen.
TRACE verwirft betroffene gerenderte Routen einschließlich SNR-Ortslabels beim
nächsten Zeichenlauf. Es werden nur ursprünglich benachbarte sichtbare Hops
verbunden; ausgeblendete Hops werden nicht übersprungen.

Der Browser behält einmal gelernte Repeater-Kollisionen bis zum Neuladen der Seite.
Dadurch können ältere HTTP-Antworten oder ein Tabwechsel die Standorte nicht wieder
einblenden. Dies gilt auch bei pausiertem Replay; dessen historische Pakete und
Positionsmodell werden nicht mit Live-Paketen ergänzt. Eine administrativ entfernte
manuelle Kollisionsidentität wird nach vollständigem Neuladen neu bewertet.

## Datenbestand und Aufwand

Keine Schemaänderung, Löschung oder Änderung gespeicherter Pakete, Nodes,
Positionen, Empfangszähler, RSSI/SNR-Statistiken oder Tabellenansichten.
Die Filterung begrenzt die Darstellung; Rohpakete und Archiv-APIs behalten ihre
bisherigen Daten und sind kein Zugriffsschutz für gespeicherte Koordinaten.

Die serverseitige Prüfung nutzt die bereits für Karte, Bootstrap, Replay oder
TRACE-Namensauflösung geladenen Node-Zeilen. Nur die kleine manuelle Referenztabelle
wird gegebenenfalls zusätzlich gelesen. Kein zusätzlicher Paketarchiv-Scan, keine
Datenbankabfrage beim Zoomen oder Zeichnen. Der Aufwand ist linear in der Zahl
bekannter Identitäten. Der Browser hält einen Präfixindex und prüft pro Standort
mit Set-Zugriffen; ein WebSocket-Batch löst höchstens eine globale Invalidierung aus.
Bestehende Nachbar-, TRACE- und Positionscaches sowie Delta-Paketdaten bleiben
erhalten. Die Replay-Metadaten zählen weiterhin gegen dessen Antwortgrößenlimit.

## Automatisierte Prüfung

Alle Datenbank- und Browser-Fixtures sind synthetisch. Kein Produktionsarchiv,
kein MQTT-/Funkzugriff, kein Deployment und kein Commit.

```bash
.venv/bin/python -m unittest discover -s tests -v
for test in tests/test_*ui.js; do deno run --allow-read=static "$test" || exit; done
.venv/bin/python tests/browser_map_visibility.py
.venv/bin/python tests/browser_map_history.py
.venv/bin/python tests/browser_map_selection.py
.venv/bin/python tests/browser_trace_map.py
.venv/bin/python tests/browser_meshlive.py
.venv/bin/python tests/browser_replay.py
```

Gezielte Regressionen in `test_map_visibility.py` und `test_map_visibility_ui.js`
prüfen eindeutige Keys, beide Kollisionspartner, mehrfache ADVERTs, Groß- und
Kleinschreibung, historische/positionslose Kandidaten, neue Kollisionen,
unveränderte andere Node-Typen und gemeinsame Verwendung in allen Karten.
Vorher-/Nachher-Datenbankdumps prüfen unveränderte Archivdaten. Karten-/Bootstrap-
Tests funktionieren auch nach Entfernen der Pakettabelle in der Testdatenbank.

`browser_map_visibility.py` prüft mit echtem Leaflet zusätzlich Positionsversatz,
Verbindungslinien samt unabhängigen Popups, veraltete HTTP-Antworten, Tabwechsel,
laufende Canvas-Animationen, bereits gezeichnete TRACE-Geometrie und pausiertes
oder noch ladendes Replay. Bestehende Browserprüfungen sichern historische Auswahl, DX-Navigation,
Zoom-/Layer-Wiederverwendung, responsive Ansichten und Replay-/Live-Trennung ab.

Ergebnis am 16.11.2026:

| Prüfung | Ergebnis |
| --- | --- |
| Python-Gesamtsuite | 214 Tests bestanden, 20,864 s |
| JavaScript-/Deno-UI-Skripte | Alle 18 Skripte bestanden |
| Neuer Kollisions-Browsertest | Alle vier Abläufe bestanden: Hauptkarte/MeshLive, TRACE, pausiertes und ladendes Replay |
| Bestehende Browser-Skripte | Historische Karte, TRACE, MeshLive und Replay bestanden |
| Kartenauswahl-/Layer-Regression | Vier normale Viewports und drei dichte Viewports mit 1600 Nodes bestanden; letzter dichter Viewport separat nach 120-s-Zeitlimit des Gesamtlaufs |
| `git diff --check` | Bestanden |

Der erste sandboxinterne Gesamtlauf blieb bei ASGI-Tests stehen; Chromium scheiterte
an einer gesperrten Socket-Operation. Die Prüfungen wurden anschließend außerhalb
der Sandbox mit denselben Offline-Fixtures ausgeführt. Produktionslast oder
Laufzeitgewinne wurden nicht gemessen.
