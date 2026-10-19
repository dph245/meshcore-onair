# Etappe 1.1 – Marker und Beschriftungen

> Folgeänderung: [Etappe 1.2](map-selection-stage1.2.md) stellt direkte Nachbarn
> unter Zoom 12 als kleine interaktive Punkte dar. Die Selektion bleibt unverändert.

## Bestandsaufnahme und Änderung

Etappe 1 verwendete bereits einen lokalen Nachbarindex und getrennte normale
und TRACE-Layer. Sie ließ alle normalen Marker sichtbar und erzwang bei
Nachbarn unter Zoom 10 die Labels. Bei vielen Nodes überdeckten deshalb
Beschriftungen und unbeteiligte Marker die selektiven Links.

Jetzt entfernt ausschließlich die normale Ansicht **Ausgewählter Repeater**
mit aktiver Auswahl alle unbeteiligten Marker samt Positionshilfslinien aus dem
Leaflet-Layer. Sichtbar bleiben Auswahl und eindeutig zugeordnete, positionierte
direkte Nachbarn. Dafür wird dieselbe geprüfte Linkmenge verwendet wie für
Linien und Richtungspfeile: keine Zuordnung anhand mehrdeutiger Kurz-Hashes,
keine erfundenen Positionen und keine Entfernungsgrenze.

Ohne Auswahl sowie in **Keine Links** und **Alle Links** bleibt die vollständige
bisherige Markerübersicht erhalten. Auswahlwechsel, Zurücksetzen, Suche, Popups,
ADVERT-Details und gespeicherter Kartenausschnitt funktionieren weiterhin.
TRACE verwendet seinen eigenen Layer; die normale Markerfilterung verändert
keine TRACE-Hops, Vergleichsrouten oder SNR-Werte.

## Zoomregel

- Der ausgewählte Repeater bleibt hervorgehoben und bei jedem Zoom beschriftet.
- In der selektiven Ansicht sind permanente Nachbarlabels bei Zoom **0–13**
  verborgen; ab **14** erscheinen sie wieder. Icons bleiben sichtbar.
- Namen sind bei verborgenen Labels per Hover und bestehendem Klick-/Touch-Popup
  erreichbar. Der Klick auf einen Nachbarrepeater wählt diesen wie bisher aus.
- Außerhalb der selektiven Ansicht bleibt die bisherige Labelregel bestehen:
  verborgen unter 10, klein bei 10–11, regulär ab 12.

Leaflet erlaubt Zoom bis 19, startet normalerweise bei 10 und erreicht die volle
Icongröße bereits bei 12. Zoom 14 trennt die lokale Detailansicht von der
regionalen Übersicht; gegenüber 12 vervierfacht sich der Pixelabstand zwischen
Standorten. Die Grenze wurde mit realem Leaflet in Chromium für 37 und 209
synthetische Nachbarn geprüft, einschließlich Desktop, Smartphone und Querformat.
Die Labelregel hängt nicht von der Nachbaranzahl ab.

Bestehende Koordinaten und Versatzregeln für identische Positionen bleiben
unverändert. Bei großem Zoom können Labels sehr dicht benachbarter Standorte
weiterhin überlappen. Es gibt bewusst keinen neuen Kollisionsalgorithmus,
keine weiteren geografischen Verschiebungen und kein Clustering. Auf kleinen
Zoomstufen können die Nachbaricons selbst weiterhin dicht übereinander liegen.

## Rendering und Speicher

- Der vorhandene lokale Index liefert die direkten Links in O(d), ohne erneute
  vollständige Linksuche bei Zoom oder Auswahlwechsel.
- Vorhandene Marker werden gezielt entfernt bzw. wieder hinzugefügt, nicht neu
  erzeugt. Neue Marker und Positionshilfslinien werden erst nach der Sichtbarkeits-
  entscheidung an die Karte angehängt.
- Ausgeblendete Markerlabels sind nicht im Karten-DOM und verursachen dort keine
  Textlayout-/Zeichenarbeit. Bei sichtbaren Nachbarn unter Zoom 14 verhindert
  CSS `display:none` das Layout der permanenten Labels.
- Markerobjekte, Popup-Inhalte und Icon-Daten bleiben im Speicher für die Rückkehr
  zur Gesamtübersicht: kein Versprechen einer O(d)-Speicherbelegung. Der vorhandene
  Markerbestand bleibt O(N), der Nachbarindex O(E).
- Sichtbarkeitsprüfung und bestehende Positions-/Versatzberechnung bleiben O(N).
  Die Berechnung bezieht weiterhin auch ausgeblendete Geräte ein, damit sich der
  bestehende Versatz nicht allein durch eine Auswahl verändert.
- Keine Backendänderung, neue SQL-Abfrage, API, Migration oder Abhängigkeit.
  Caches, ETags und Aktualisierungsintervalle sind unverändert.
- Browsertests messen Schicht-/DOM-Zahlen und Abrufe, keine Produktions-FPS oder
  Heap-Größe.

## Geänderte Dateien

| Datei | Änderung |
|---|---|
| [static/map.js](../static/map.js) | Selektive Layer-Sichtbarkeit, Fokusklasse, Zoomgrenze; neue Marker/Hilfslinien nicht vor der Filterentscheidung anhängen. |
| [static/style.css](../static/style.css) | Zoomabhängige Nachbarlabels, dauerhaftes Auswahl-Label und Hover-Namen. |
| [tests/test_neighbors_ui.js](../tests/test_neighbors_ui.js) | Marker-/Hilfslinienfilter, Auswahlwechsel, leere Nachbarn und Rücksetzen; vorhandene Index-/Richtungstests. |
| [tests/browser_map_selection.py](../tests/browser_map_selection.py) | Angepasste Markererwartung; 1.600 Nodes mit 37/209 Nachbarn, Zoom 7/10/12/13/14, Refresh, Objektwiederverwendung und Popups. |
| [tests/browser_trace_map.py](../tests/browser_trace_map.py) | TRACE-Vergleich zusätzlich mit zuvor ausgewähltem normalem Marker prüfen. |
| [README.md](../README.md) | Aktuelles Bedienverhalten. |
| [map-selection-stage1.md](map-selection-stage1.md), dieses Dokument | Folgeänderung kennzeichnen und Etappe 1.1 dokumentieren. |

## Tests

Alle Prüfungen offline mit synthetischen Daten bzw. temporären Testdatenbanken:

- 134 Python-Tests bestanden.
- Alle 16 JavaScript-UI-Testskripte bestanden.
- Selektive Browserkarte: vier Bildschirmgrößen, Suche nach Namen/Keys,
  mehrdeutiges `dd4c42`, Fernverbindung, Modi, Auswahlwechsel und Rücksetzen.
- Lastfälle: 1.600 Nodes; ÖselPieter mit 37 und Brocken3 mit 209 direkten Nachbarn,
  jeweils nur 38 bzw. 210 Marker im DOM. Daten sind synthetisch, keine Kopie der
  realen Nachbartopologie. Desktop 1280×900, Smartphone 390×844, Querformat 844×390.
- Unter Zoom 14 genau ein permanentes Label; ab 14 alle sichtbaren Repeaterlabels.
  Wiederholte Wechsel und Node-Refresh erhalten Markeridentitäten; nur ein
  initialer Linkabruf für die gesamte Auswahl-/Zoomfolge.
- TRACE: Desktop/Mobil, zwei Vergleichsrouten und acht SNR-Werte über alle drei
  normalen Linkmodi, einschließlich zuvor gesetzter normaler Markerauswahl.
- MeshLive und Replay: bestehende Browserregressionen bestanden.
- Responsive: alle 14 Tabs auf neun Bildschirmgrößen bestanden.
- Querformat: Rotation, Safe-Area, Scrollen und beide Kartengrößen geprüft.
- `git diff --check`: keine Whitespacefehler.

Reproduktion wie in Etappe 1: `deno run --allow-read=static tests/test_neighbors_ui.js`,
`python -m unittest discover -s tests -p 'test_*.py'` und die genannten
`tests/browser_*.py` mit Playwright sowie lokalem Chromium. Die vorhandene
temporäre Playwright-Installation liegt unter `/tmp/onair-browser-test-deps`.
Die Lastfall-Screenshots werden unter `/tmp/onair-dense-<Breite>x<Höhe>.png` abgelegt;
Kartenkacheln werden im Offline-Test simuliert.

Keine Änderungen an produktiven Daten und keine produktive Bereitstellung.
