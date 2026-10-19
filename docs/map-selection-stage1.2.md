# Etappe 1.2 – Zoomabhängige Punktdarstellung

## Bestandsaufnahme: MeshLive

MeshLive verwendet keine CircleMarker, sondern normale Leaflet-Marker mit
`L.divIcon`. Ein `span.meshlive-node-dot` bildet den Kreis:
8 px Basisdurchmesser, 1 px weiße Kontur, gerätespezifische Farbe und leichter
Schatten. MeshLive variiert den Durchmesser abhängig vom Zoom zwischen 6 und
14 px. Die transparente Markerfläche beträgt dort 24 × 24 px.
Tooltip und Popup sind am Marker gebunden; Updates verwenden vorhandene Marker,
aktualisieren Position/Icon und Popup-Inhalte. Empfangspulse skalieren den Punkt.

Die normale Karte verwendet dieselbe Punkt-CSS-Klasse einschließlich Farbe,
Kontur und Schatten. MeshLive selbst, seine Zoomgrößen und Animationen bleiben
unverändert. Die normale Karte verwendet einen konstanten Durchmesser von 8 px
innerhalb ihrer kleinen Zoomstufen.

## Umsetzung und Bedienung

Nur in der normalen Ansicht **Ausgewählter Repeater** mit aktiver Auswahl:

| Zoom | Ausgewählter Repeater | Eindeutige direkte Nachbarn |
|---|---|---|
| 0–11 | Hervorgehobenes Icon mit Name | 8-px-Punkte ohne permanente Labels |
| 12–13 | Hervorgehobenes Icon mit Name | Normale Icons ohne permanente Labels |
| 14–19 | Hervorgehobenes Icon mit Name | Normale Icons mit Labels |

Die vorgegebenen Grenzen passen zur bestehenden Konfiguration: volle Icongröße
ab Zoom 12, Nachbarlabels ab 14 und maximale Kartenzoomstufe 19. Die Browserprüfung
deckt 7, 10, 11, 12, 13 und 14 sowie wiederholte Übergänge ab.

Jeder bestehende Icon-Inhalt erhält zusätzlich einen zunächst versteckten Punkt.
Eine Zoomklasse am Kartencontainer schaltet per CSS zwischen Symbol und Punkt um;
die bestehenden Fokus-/Nachbarklassen begrenzen dies auf direkte Nachbarn.
Der ausgewählte Repeater ist ausdrücklich ausgenommen. Aufheben der Auswahl und
die Modi **Keine Links**/**Alle Links** stellen die unveränderte Iconübersicht her.

Das Leaflet-Markerobjekt, sein Anker, seine Position und die transparente
**36 × 36 px große Trefferfläche** bleiben unverändert. Der sichtbare 8-px-Punkt
sitzt in deren Mitte. Klick bzw. Touch auch neben dem sichtbaren Kreis öffnet
weiterhin das vorhandene Geräte-/ADVERT-Popup und wählt den Nachbarrepeater aus.
Hover zeigt seinen Namen. Die Punktdarstellung erzeugt keinen zweiten Layer,
kein separates Klickziel und keinen neuen Popup-Inhalt.

Bestehender Positionsversatz, Linienendpunkte, Richtungspfeile, Identitätsprüfung,
Fernverbindungen und Nachbarindex bleiben unverändert. Keine neue Zuordnung aus
Kurz-Hashes. Keine Änderungen an TRACE, MeshLive, Replay oder deren Decodern.

## Performance und Grenzen

- Zoomwechsel erzeugen weder neue Marker noch Icons; CSS ändert ihre Darstellung.
  Auch Auswahlwechsel verwenden die bestehenden Markerobjekte.
- Ein zusätzlicher kleiner Span je normalem Marker: geringer zusätzlicher O(N)-
  Speicherbedarf, kein zweiter Markerbestand und keine zusätzlichen Eventhandler.
- Unbeteiligte Marker bleiben wie in Etappe 1.1 vom Karten-DOM entfernt.
- Keine neuen Backend-Anfragen, Endpunkte, SQL-Operationen oder Datenbankänderungen.
  Caches, ETags und Refreshintervalle bleiben unverändert.
- Vorhandene O(N)-Positions-/Versatzberechnung und Sichtbarkeitsprüfung bleiben
  bestehen; normale Links werden weiter aus dem lokalen O(d)-Nachbarindex gezeichnet.
- Die große transparente Trefferfläche erleichtert Touch, kann bei nahen Punkten
  aber mit anderen Trefferflächen überlappen. Dann hilft Hineinzoomen. Es gibt
  weder Clustering noch eine neue Auswahl-/Kollisionslogik.
- Punkte und Linien können bei sehr dichter Topologie weiterhin überlappen.
  Tests messen Marker-/DOM-Zahlen und Requests, keine Produktions-FPS oder Heapgröße.

## Geänderte Dateien

| Datei | Änderung |
|---|---|
| [static/map.js](../static/map.js) | Zoomklasse unter 12; zusätzlicher Span mit vorhandener MeshLive-Punktklasse. |
| [static/style.css](../static/style.css) | Auf normale selektive Nachbarn begrenzter Wechsel Symbol/Punkt. |
| [tests/browser_map_selection.py](../tests/browser_map_selection.py) | Punkt-/Icon-Zahlen, Zoomgrenzen, echter Klick/Touch außerhalb des sichtbaren Punktes, Hover, Auswahlwechsel und deutschlandweit verteilte synthetische Nachbarn. |
| [README.md](../README.md) | Drei Darstellungsstufen beschrieben. |
| [map-selection-stage1.1.md](map-selection-stage1.1.md), dieses Dokument | Folgeänderung und Ergebnisse dokumentiert. |

## Tests

Offline mit lokalem Chromium, simulierten API-Antworten/Kartenkacheln und
temporären Python-Testdatenbanken; keine Produktivdaten:

- 134 Python-Tests bestanden.
- Sämtliche 16 JavaScript-Testskripte bestanden.
- Selektive Karte: 1.600 bekannte Nodes, synthetischer ÖselPieter mit 37 und
  Brocken3 mit 209 Nachbarn; Desktop, Smartphone und Querformat.
  Nur 38 bzw. 210 Marker vorhanden, bei Zoom unter 12 genau 37 bzw. 209 Punkte
  und ein ausgewähltes Icon. Ab 12 keine sichtbaren Punkte.
- Unter Zoom 14 genau ein permanentes Label; ab 14 Labels aller sichtbaren
  Repeater. Wiederholtes Zoomen, Auswahlwechsel und Node-Refresh erhalten die
  Markerobjekte. Die Auswahl-/Zoomfolge benötigt nur einen initialen Linkabruf.
- Echte Browser-Klicks und emulierte Touch-Taps 10 px neben dem Punktzentrum
  (außerhalb seines Radius) öffnen das bestehende Popup und wechseln die Auswahl.
  Hover liefert den Namen. Der gewählte Punkt wird sofort zum hervorgehobenen Icon.
- Suche einschließlich mehrdeutigem `dd4c42`, Vollkey, Fernverbindung, Reset und
  Moduswechsel aus der vorhandenen Browserprüfung weiterhin bestanden.
- TRACE-Vergleich mit zwei Routen und acht SNR-Werten, MeshLive und Replay:
  bestehende Browserregressionen bestanden.
- Responsive: alle 14 Tabs auf neun Bildschirmgrößen. Querformat zusätzlich mit
  Rotation, Safe-Area, Scrollen und Größenprüfung beider Karten.
- `git diff --check`: keine Whitespacefehler.

Die synthetischen Nachbarn bilden keine reale Topologie der genannten Geräte ab.
Screenshots unter `/tmp/onair-dense-<Breite>x<Höhe>.png` zeigen die Punktansicht;
die Offline-Kartenkacheln sind leer. Touchprüfung erfolgte per Chromium-Emulation,
nicht auf physischer Smartphone-Hardware.

Reproduktion:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
for test in tests/test_*_ui.js; do deno run --allow-read=static "$test" || exit; done
PYTHONPATH=/tmp/onair-browser-test-deps .venv/bin/python tests/browser_map_selection.py
PYTHONPATH=/tmp/onair-browser-test-deps .venv/bin/python tests/browser_trace_map.py
PYTHONPATH=/tmp/onair-browser-test-deps .venv/bin/python tests/browser_meshlive.py
PYTHONPATH=/tmp/onair-browser-test-deps .venv/bin/python tests/browser_replay.py
PYTHONPATH=/tmp/onair-browser-test-deps .venv/bin/python tests/browser_responsive.py
PYTHONPATH=/tmp/onair-browser-test-deps .venv/bin/python tests/browser_landscape.py
```

Playwright liegt nur in der vorhandenen temporären Testinstallation;
keine neue Anwendungsabhängigkeit, Migration oder produktive Bereitstellung.
