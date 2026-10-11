# Responsive Optimierung – 11. Oktober 2026

## Bestandsaufnahme und Umsetzung

Alle 14 Tabs verwenden weiterhin die vorhandenen Ansichten, Datenabfragen und
Aktualisierungsmechanismen. Kein Framework-Wechsel, keine Abhängigkeiten,
Backendänderungen, Dienste, Container oder Änderungen produktiver Daten.
Kein Deployment.

| Ansicht / Komponente | Ausgangslage | Umsetzung |
| --- | --- | --- |
| Gemeinsamer Kopf und Navigation | Tabs umbrechend; auf 320 px wenig Resthöhe, kleine Bedienelemente | Bis 950 px eine horizontal scrollbare Tabzeile, mindestens 44 px hohe Tabs; aktive Auswahl nach Wechsel und Rotation sichtbar; kompakter Kopf, Safe-Area-Abstände |
| Live | Tabelle bereits scrollbar, aber Filter und Tabelle teilen den Scrollbereich; schmale Resthöhe | Eigener Tabellen-Scrollbereich, mobile Filter ein-/ausklappbar, Filterstatus bleibt sichtbar; Paketdetails auf Bildschirmbreite umgebrochen; Pause bleibt erreichbar |
| Rohdaten | Zeilenumbruch und dynamische Viewporthöhe bereits vorhanden | Mindesthöhe für Terminalinhalt; bei wenig Höhe vertikal scrollbar; Checkbox und Label touchfreundlich |
| Observer A / B | Tabelle bereits in `.noise-scroll` | Auswahlfelder begrenzt und umbrechend, 44 px Höhe; lange Observernamen verursachen keinen Seitenüberlauf |
| Repeater | Bereits einspaltige Karten unter 800 px; Historie in `.noise-scroll` | Gemeinsame Touch- und Formularregeln, sichere Breiten für lange Namen und geöffnete Historien |
| Channels | Nachrichten und Empfangsdetails bereits umbrechend | Touchfreundliche Kanalauswahl und aufklappbare Details |
| Archiv | Flexible Form, aber intrinsische Feldbreiten und Datumsfelder problematisch | Begrenzte Feldbreiten und flexible Formularspalten; 16 px Eingabeschrift auf kleinen Displays verhindert iOS-Fokuszoom; Details umbrechend |
| Nodes | Schlüssel und Details bereits umbrechend | Suchformular und Nachladebedienung mit gemeinsamen Regeln |
| Map | Desktopkarte und Sidebar vorhanden; mobil starre 60-dvh-Karte plus lange Sidebar | Kleine Hochformate: Karte und begrenzt scrollbare Sidebar; Querformat: Karte neben Sidebar; Zoom-/Schließtasten 44 px, Popupinhalt durch tatsächliche Kartenhöhe begrenzt |
| Nachbarn | Tabelle bereits lokal scrollbar | Suchfeld, Richtungsfilter und Sortierbuttons touchfreundlich; Navigation und Statistiktexte umbrechen |
| Routen | Formularfelder mit Mindest-/Eigenbreiten; Karten bereits textflexibel | Formularfelder passen in 320 px; Richtungswahl, Tauschen und Suche erreichbar; Routenkarten umbrechend |
| Discovery | Native Details und Texte bereits flexibel | Touchfreundliche Zusammenfassungen und Zeitraumauswahl |
| TRACE | Verlauf bereits in eigenem Scrollcontainer | Routenwahl auf verfügbare Breite begrenzt; gemeinsame Form-/Touchregeln; lange Legenden und Details umbrechen |
| Noise Floor | SVG-Diagramme bereits lokal scrollbar, Tooltip außerhalb | Gemeinsame Containerbegrenzung; Messpunktinteraktion und Tooltip im Browser geprüft |
| MeshLive | Referenz: kompakte Navigation, mobile Optionen, dynamische Kartenhöhe, ResizeObserver | Vorhandene Animation-/Replay-/Audio-Bedienung erhalten; gemeinsame Tab-Sichtbarkeit, sichere Popuphöhe und zusätzliche Tabletprüfung |

Vorhandene `.archive`, `.noise-scroll`, `.map-sidebar`, `.map-toolbar` und
Formularstrukturen wurden weiterverwendet. Desktopregeln bleiben überwiegend
unverändert; Live erhält auch dort den eigenen Tabellencontainer. Es gibt keine
separaten Modal-Dialoge: Detailansichten sind native `details`-Elemente oder
Leaflet-Popups.

Ein im Touchtest reproduzierter Leaflet-Fokusfehler wurde behoben: Leaflet stellt
beim Fokussieren nur den Scrollstand des Fensters wieder her. In einer gescrollten
Kartenansicht verschob sich dadurch das Panel zwischen Touch und Klick. Der
Kartencontainer wird nun vor Leaflets Mausbehandlung mit `preventScroll` fokussiert;
Tastatursteuerung und Markerbedienung bleiben erhalten.

## Prüfverfahren

`tests/browser_responsive.py` nutzt das vorhandene Offline-Playwright-Harness:
alle API-Antworten, WebSocket-Pakete und Kartenkacheln sind Fixtures. Kein
Anwendungsserver, MQTT oder Archivzugriff. Befüllte Tabellen, lange Namen und
Schlüssel, geöffnete Empfangs-/Discovery-/TRACE-Details, Repeaterhistorien und
Diagramme gehören zur Prüfung, nicht nur leere Ansichten.

Die Matrix umfasst 320 × 568, 375 × 667, 390 × 844, 430 × 932, 844 × 390,
768 × 1024 und 1440 × 900. Jede Größe prüft alle Tabs, Seiten-/Main-Überläufe,
horizontale Erreichbarkeit der Bedienelemente und aktive Tab-Sichtbarkeit.
Zusätzlich: Filter/Reset/Pause/Resume, Observerauswahl, Suche, Sortierung,
Routentausch, Kartendetails, Diagramm-Messpunkte, Tastaturnavigation und Rotation.
Screenshots entstehen unter `/tmp/onair-responsive/`.

MeshLive hat einen separaten Touchtest für Verschieben, Pinch-Zoom, Zoomtasten,
Audio-Schalter, Animation, Replay, Tabwechsel und Resize einschließlich veränderter
Browserhöhe. Die Tabletgröße wurde ergänzt. Der Live-Regressionshelfer öffnet bei
Bedarf die mobilen Filter; der Vergleich mit `HEAD` prüft unveränderte Paketdaten-
Darstellung unabhängig vom neuen umgebenden Layout.

Befehle (Python mit installiertem Playwright und `/usr/bin/chromium`):

```sh
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
for test in tests/test_*_ui.js; do deno run --allow-read "$test" || exit; done
python tests/browser_responsive.py
python tests/browser_meshlive_mobile.py
python tests/browser_meshlive.py --compare-ref HEAD
python tests/browser_replay.py
python tests/browser_harp.py
```

In dieser Arbeitsumgebung wurde für Playwright die bereits vorhandene
Python-Umgebung `/home/oliver/src/talli-air/.venv/bin/python` verwendet; keine
Installation nötig. Chromium und der HTTP/WebSocket-Pythontest benötigen hier
einen Lauf außerhalb der Sandbox.

## Ergebnis

- 110 Python-Tests erfolgreich (Decoder, Archiv, API, WebSocket, Nachbarn,
  Routen, Replay und weitere bestehende Funktionen).
- Alle 15 JavaScript-UI-/Modelltests erfolgreich.
- 98 Tab-/Viewport-Kombinationen erfolgreich: 14 Tabs × 7 Größen; keine
  unbeabsichtigten horizontalen Seiten-/Main-Überläufe in den Prüffällen.
- MeshLive-Touchmatrix in allen 7 Größen erfolgreich, einschließlich Tablet,
  Hoch-/Querformat und dynamischer Höhenänderung.
- Bestehende MeshLive-, Replay- und Harp-Browsertests erfolgreich; Paketdarstellung
  und bisherige Tabreihenfolge im Vergleich mit `HEAD` unverändert.
- Screenshots ausgewählter Smartphone-, Querformat- und Desktopansichten visuell
  geprüft; `git diff --check` ohne Befund.

## Verbleibende Grenzen

- Browserprüfung mit Chromium und emulierten Viewports/Touch, keine physischen
  iOS-/Android-Geräte oder Safari-Prüfung. Safe-Area-CSS ist vorhanden; reale
  Displayausschnitte, Bildschirmtastaturen und Browserleisten sind damit nicht
  vollständig nachgebildet.
- Große Tabellen und dichte Messdiagramme bleiben bewusst lokal horizontal
  scrollbar; Diagramm-Mindestbreiten erhalten lesbare Achsen und Messpunkte.
- Auf sehr niedrigen Displays ist vertikales Scrollen in Panel, Kartenbedienung
  oder Popup erforderlich. Es werden keine Funktionen entfernt.
- Offline-Fixtures prüfen Bedienung und Darstellung. Bestehende Modell-, API-
  und WebSocket-Tests sichern Berechnung und Datenfluss separat ab; ein Test
  gegen den produktiven MQTT-Strom wurde nicht vorgenommen.

## Nachbesserung: Smartphones mit niedriger Querformathöhe

Ursache: Header und Navigation verwenden weder `fixed` noch `sticky`. Die
Live-/Rohdaten-/Kartenansichten begrenzen den Body auf `100dvh`; Header, Toolbar
und Tabs schrumpfen nicht mit, während nur Panel/Sidebar scrollen. Dadurch
bleiben bis zu 188 px oberhalb des Inhalts dauerhaft sichtbar. MeshLive benötigt
zwar nur 106 px, stapelte unter 701 px aber zusätzlich Karte und Bedienung auch
im Querformat. `sticky` wird für Tabellenköpfe genutzt, nicht für den Seitenheader.

Die gezielte Ergänzung gilt ausschließlich für `orientation: landscape`,
Breite bis 950 px und Höhe bis 500 px:

- Eine normale Grid-Zeile enthält horizontal scrollbare Tabs, Verbindungsstatus,
  Theme-Schalter und die vorhandene Pause-Taste. Keine absolute Positionierung,
  Überlagerung oder Scroll-Animation. MeshLive behält seine eigene Pause-Bedienung.
- Logo, Radio-/Noise-Kurzinfo, globaler Paketzähler und Footer entfallen nur in
  diesem kompakten Modus; Filterstatus und fachliche Inhalte bleiben verfügbar.
- Der Inhalt nutzt den restlichen `100dvh`-Bereich. Normale Tabs scrollen im Main;
  Kartenbedienungen scrollen in ihrer Sidebar. Beide Karten stehen auch bei
  667 px neben ihrer Bedienung. Vorhandene Safe-Area-Abstände bleiben erhalten.
- Ein ResizeObserver auf der Tabzeile hält die aktive Auswahl auch dann sichtbar,
  wenn sich deren Breite durch Safe Areas oder benachbarte Bedienelemente ändert.
  Die vorhandenen Karten-/Canvas-ResizeObserver bleiben unverändert.

Gemessene Höhen ohne zusätzliche Safe-Area-Abstände:

| Viewport | Kopf/Toolbar/Tabs vorher → nachher | MeshLive-Karte vorher → nachher |
| --- | --- | --- |
| 667 × 375 | 188 → 53 px (MeshLive: 106 → 53 px) | 158 → 309 px |
| 844 × 390 | 188 → 53 px (MeshLive: 106 → 53 px) | 271 → 324 px |
| 932 × 430 | 188 → 53 px (MeshLive: 106 → 53 px) | 311 → 364 px |

Zusätzliche Prüfung `tests/browser_landscape.py`: alle 14 Tabs in den drei
Querformatgrößen, Rotation, um 80 px verringerte Viewporthöhe, Sidebar-/Main-
Scrollen, aktive Tabs innerhalb der Tabzeile, nicht überlappende Kartenbereiche,
Leaflet-/Canvas-Größen und simulierte Safe-Area-Abstände. Der Geometrievergleich
mit der bisherigen CSS-Datei bestätigt unveränderte Hochformat-/Tablet-/Desktop-
Layouts bei 375 × 667, 390 × 844, 768 × 1024 und 1440 × 900.

Die allgemeine Responsiv- und MeshLive-Touchmatrix wurde um 667 × 375 und
932 × 430 erweitert: alle 126 Tab-/Viewport-Kombinationen und alle neun MeshLive-
Größen erfolgreich, einschließlich Touch-Pan, Pinch-Zoom, Audio-Schalter, Replay
und Resize. Alle 15 JavaScript-Tests erfolgreich. Screenshots unter
`/tmp/onair-landscape-*.png` wurden visuell geprüft.

Browseremulation ersetzt weiterhin keinen Test auf einem physischen Smartphone;
Safe Areas werden durch entsprechende Abstände simuliert. Keine Änderung an
Backend, Datenlogik oder Audioimplementierung; kein Deployment.
