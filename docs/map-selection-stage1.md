# Kartenübersicht und selektive Links – Etappe 1

Stand: 19. Oktober 2026. Implementierung auf Basis des vorigen Standes `d567222`;
der Zwischenstand wurde während der Arbeit als `4f9e7e1` übernommen.

## Verhalten

- Die Karte startet mit **Ausgewählter Repeater**, ohne Auswahl und ohne normale Links.
  Eine zuvor gespeicherte Einstellung der alten Link-Checkbox wird nicht übernommen.
- **Keine Links** zeigt die bisherigen Node-Marker ohne normale Funkstrecken.
- **Ausgewählter Repeater** zeigt nur dessen eindeutig zuordenbare direkte
  Nachbarverbindungen, einschließlich beider vorhandener Richtungszähler und Pfeile.
  Unbeteiligte Marker bleiben sichtbar. Der ausgewählte Marker erhält eine deutliche
  Umrandung; die Auswahl wird oberhalb der Karte benannt.
- **Alle Links (Expertenmodus)** zeigt alle bisher darstellbaren Verbindungen, auch
  wenn ein Repeater ausgewählt ist. „Auswahl aufheben“ ändert diesen expliziten Modus nicht.
- Kartenbewegung, Zoom und regelmäßige Datenaktualisierung behalten die Auswahl.
  Ein Wechsel ersetzt sie. „Auswahl aufheben“, Klick auf freie Karte und die bereits
  vorhandene Aktion „Alle Nodes anzeigen“ löschen sie. Verschwindet ein Marker wegen
  der bisherigen Daten-/Altersregeln, wird auch seine Auswahl aufgehoben.
- Suche nach Namen (Teiltext) oder Public Key (Präfix bis Vollkey), ohne Beachtung
  der Groß-/Kleinschreibung. Treffer zeigen Namen und vollständigen bekannten Key.
  Mehrdeutige Eingaben wählen nichts automatisch aus, auch nicht per Enter.
- Die Auswahl eines Suchtreffers aktiviert den selektiven Pfadmodus, zentriert die
  Karte und öffnet das bestehende Node-Popup einschließlich ADVERT-Details.
- Alle bekannten Repeater bleiben in der Suchliste, auch wenn sie wegen fehlender
  Position oder mindestens vier Wochen Inaktivität nicht auf der Karte erscheinen.
  Diese Treffer sind mit dem Grund gekennzeichnet und nicht auswählbar; bestehende
  Alters-/Positionsregeln werden nicht umgangen. Jeweils 30 weitere Treffer sind
  über „Weitere Treffer“ erreichbar.
- Die bisherigen Ansichten bleiben erreichbar: „Repeater / Nodes“ setzt normale
  Links auf „Keine“, „Pfade“ aktiviert bei Bedarf „Ausgewählter Repeater“.
  „TRACEs“ verwendet weiterhin seinen eigenen Layer. Änderungen am normalen
  Linkmodus entfernen weder TRACE-Auswahl noch TRACE-Linien oder SNR-Beschriftungen.
  Die Repeater-Suche führt ausdrücklich zurück zur normalen Pfadansicht; ein späterer
  Wechsel zu TRACEs zeigt die zuvor ausgewählten TRACE-Empfänge wieder.

Keine neuen Accordions, keine Cluster und keine Änderungen an der Interpretation
von Funkstrecken, TRACE-/DISCOVER-Decodierung oder historischen Positionen. Die
kleinen Verbindungslinien zwischen versetzten Markern und ihrem tatsächlichen
Standort bleiben erhalten: Sie sind keine Funkstrecken.

## Bestehende Layer und Performance

Vorher lud die Karte die vollständige kompakte Nachbarliste und zeichnete bei
aktivierter Checkbox sämtliche Links. Eine Repeater-Auswahl entfernte außerdem
unbeteiligte Marker. Jetzt wird derselbe `neighborLayer` nur selektiv befüllt;
Node-Marker und der separate TRACE-Layer bleiben eigenständig.

| Vorgang | Verhalten nach Etappe 1 |
|---|---|
| Frischer Kartenstart | Keine Anfrage an `/api/repeater-neighbors/map`, keine normalen Link-Geometrien. Node-Daten werden wie bisher geladen. |
| Erste Auswahl / Expertenmodus | Ein Abruf des bestehenden kompakten Endpunkts. Er überträgt weiterhin alle darstellbaren Links, nicht nur die ausgewählten. |
| Antwort geändert | Lokaler Index `Public Key → direkte Links` wird einmal aufgebaut; zwei Referenzen je normalem Link, keine Kopie seiner Geometrie. |
| Auswahlwechsel | Bei bereits geladenen Daten kein Abruf; nur die Links des ausgewählten Vollkeys werden durchlaufen und als Linien/Pfeile erzeugt. |
| Zoom / Verschieben | Keine Linkabfrage. Bei Zoom werden vorhandene Markerpositionen/Versatz und die benötigten Pfeilgeometrien neu berechnet. |
| Regelmäßiger Linkrefresh | Nur bei benötigten normalen Links, weiterhin alle 30 Sekunden mit ETag/304 und vorhandenem Servercache. |
| Suche / weitere Treffer | Lokaler Filter des bereits gelieferten Verzeichnisses, keine Anfrage pro Tastendruck oder Trefferseite. |
| Node-Aktualisierung | Weiterhin alle fünf Sekunden. `/api/map-nodes` ergänzt ein kompaktes `repeaters`-Verzeichnis aus den bereits gelesenen SQL-Zeilen; keine zusätzliche SQL-Abfrage. |

Bei `E` gesamten Links und `d` direkten Links einer Auswahl reduziert sich der
Linkdurchlauf beim Zeichnen von `O(E)` auf `O(d)`; ohne Linkanzeige wird keine
Linkgeometrie erzeugt. Die bestehende Marker-Verarbeitung bleibt `O(N)` und ohne
Clustering. Der Index benötigt `O(E)` zusätzlichen Referenzspeicher. Das neue
Repeater-Verzeichnis vergrößert die Node-Antwort um Vollkeys, Namen und gegebenenfalls
Nichtverfügbarkeitsgründe; die vorhandenen Markerinformationen bleiben kompatibel.

Der Browserintegrationstest belegt: Start ohne Linkabruf; erste Auswahl genau ein
Abruf; Wechsel, Suche und Zoom innerhalb des Refreshintervalls ohne weiteren Abruf.
Ein JS-Test verhindert, dass der selektive Zeichenweg die gesamte Linkliste iteriert.
Es wurden keine Durchsatz- oder Produktionslastzahlen erhoben. Die bestehende
30-Sekunden-Cachefrist und der nächste regelmäßige Refresh bestimmen weiterhin die
Aktualität; es gibt keine neue unmittelbare Einzelabfrage beim Auswahlwechsel.

## Geänderte Dateien

Die Liste umfasst die gesamte Etappe einschließlich des zwischenzeitlich übernommenen
Commits, nicht nur den zuletzt uncommitteten Rest.

| Datei | Änderung |
|---|---|
| [static/map.js](../static/map.js) | Drei Modi, persistente Auswahl innerhalb der Sitzung, Hervorhebung, lokale Suche, Nachbarindex und bedarfsabhängiger Linkabruf. |
| [static/index.html](../static/index.html) | Offene Such-/Auswahlleiste oberhalb der bestehenden Karte; alte Checkbox ersetzt. |
| [static/style.css](../static/style.css) | Kompakte Leiste, Suchtreffer, Markierung, Smartphone-/Querformatanpassung. |
| [static/trace-map.js](../static/trace-map.js) | Anbindung der vorhandenen Ansichtsbuttons an die neuen normalen Linkmodi; TRACE-Zeichen-/SNR-Logik unverändert. |
| [onair_archive.py](../onair_archive.py) | Zusätzliche `repeaters`-Antwortliste aus der vorhandenen Node-Abfrage; keine Schreibänderung oder Migration. |
| [tests/browser_map_selection.py](../tests/browser_map_selection.py) | Neuer Offline-Test mit echter Leaflet-Karte für Auswahl, Suche, Kollisionen, Fernlink, Modi, Größen und Request-Zähler. |
| [tests/test_neighbors_ui.js](../tests/test_neighbors_ui.js), [tests/test_neighbors_fetch_ui.js](../tests/test_neighbors_fetch_ui.js) | Neue Standardsicht, Marker bleiben sichtbar, Auswahlwechsel, Indexnutzung, bedarfsabhängiger Abruf, bestehende ETags. |
| [tests/test_map_advert.py](../tests/test_map_advert.py), [tests/test_meshlive.py](../tests/test_meshlive.py) | Suchkandidaten trotz fehlender Position/Inaktivität und kompatible erweiterte API-Antwort. |
| [tests/browser_trace_map.py](../tests/browser_trace_map.py) | Zwei TRACE-Routen samt acht SNR-Werten über alle normalen Linkmodi erhalten. |
| [tests/browser_responsive.py](../tests/browser_responsive.py), [tests/browser_landscape.py](../tests/browser_landscape.py) | Neue Bedienelemente; zusätzlicher Platz für die offene Leiste wird im Layouttest berücksichtigt. |
| [tests/browser_meshlive.py](../tests/browser_meshlive.py), [tests/test_manual.py](../tests/test_manual.py) | Bereits veraltete Testerwartungen korrigiert, siehe unten. |
| [.gitignore](../.gitignore) | Neuen Browser-Test von der allgemeinen `tests/*`-Ignorierregel ausnehmen. |
| [README.md](../README.md), dieses Dokument | Bedienung, Implementierung, Performance und Prüfungen dokumentiert. |

`docs/beacon-analysis.md` stammt aus dem vorangegangenen Analyseauftrag und ist
kein Implementierungsbestandteil dieser Etappe.

## Prüfung

Alle Prüfungen liefen mit temporären Datenbanken oder simulierten Browserantworten.
Kein Produktivserver, MQTT-Verbindungsaufbau oder produktiver Datenbankzugriff wurde
für die Browserprüfung verwendet. Chromium ist vorhanden; das fehlende Python-Paket
Playwright wurde ausschließlich unter `/tmp/onair-browser-test-deps` bereitgestellt.
OnAirs Abhängigkeitsdateien und `.venv` wurden dadurch nicht erweitert.

| Prüfung | Ergebnis |
|---|---|
| Python `unittest discover -s tests -p 'test_*.py'` | 134 Tests bestanden. |
| Alle `tests/test_*_ui.js` mit Deno | 16 Skripte bestanden, einschließlich TRACE, Discovery, Nachbarn, Routen, Replay und Repeater. |
| `browser_map_selection.py` | Desktop 1280×900, Smartphone 390×844 und 320×568, Querformat 844×390; alle Auswahl-/Suchabläufe bestanden. |
| `browser_trace_map.py` | Desktop/Mobil, zwei Routen, fehlende historische Positionen, Hin-/Rückweg-SNR, acht Werte über alle drei Linkmodi, keine Abfrage bei Kartenbewegung: bestanden. |
| `browser_responsive.py` | Alle 14 Tabs an neun Größen von 320×568 bis 1440×900; keine seitlichen Überläufe, Formulare, Details, Navigation und Rotation bestanden. |
| `browser_landscape.py` | Drei Querformate, Rotation, verkleinerte Höhe, Safe-Area-Simulation und Größenabgleich beider Karten bestanden; übrige Seitengeometrie unverändert. |
| `browser_meshlive.py --compare-ref d567222` | Live-Darstellung und Tabreihenfolge wie vor der Etappe; MeshLive-Layer, Popup, Pause, Snapshot, mobile Nutzung bestanden. |
| `browser_replay.py` | Begrenzter Abruf, 10×-Zeitleiste, Pause, Ende, Tabwechsel, Abbruch und mobile Nutzung bestanden. |
| `browser_distance.py` | Fernanalyse, Richtungen, Belege, Pagination, Filter, Fehler und mobile Darstellung bestanden. |
| `browser_harp.py` | Bestehende Ton-/Animationstests auf Desktop und Mobil bestanden. |
| `browser_meshlive_mobile.py` | Neun Bildschirmgrößen, Pan/Zoom, Ton, Replay, Tabs und Resize bestanden. |
| `git diff --check` | Keine Whitespacefehler. |

Gezielt geprüft wurden außerdem:

- `dd4c42a1…`, `dd4c42d1…`, `dd4c42b1…` sowie ein nicht kartierbarer weiterer
  Kandidat: alle Treffer sichtbar, keine automatische Identitätszuordnung;
- case-insensitive Namens-/Präfixsuche, Vollkey, leere Trefferliste, mehr als 30
  Kandidaten und sichere Textdarstellung von `<test>`;
- eine 16.000-km-Verbindung bleibt in der Auswahl und behält Richtungspfeile;
- „Keine“ lässt Auswahl/Marker bestehen; „Alle“ ignoriert die Linkselektion bewusst;
  „Ausgewählt“ stellt sie wieder her; Aufheben zeigt im Standardmodus keine Linien;
- Auswahl bleibt bei Datenrefresh und beim Rückwechsel aus TRACE erhalten;
- vorhandene Popups, Richtungszähler und Verbindungsdetails bleiben erreichbar.

### Korrigierte alte Testerwartungen

Der unveränderte Stand `d567222` scheitert bereits im Manual-Migrationstest an der
Erwartung Schema 13, während die Anwendung dort schon Schema 14 verwendet. Nur die
Testerwartung wurde auf 14 korrigiert; keine Migration wurde hinzugefügt oder geändert.
Der MeshLive-Browsertest erwartete fest 14 Assets, obwohl der alte HTML-Stand bereits
16 einbindet. Jetzt prüft er die tatsächliche vollständige Assetmenge einschließlich
Versionsparametern. Der responsive Test suchte noch ein Repeater-Accordion, obwohl die
Repeater-Diagramme bereits offen angezeigt werden. Auch dieser veraltete Klick entfällt.
Im Querformat wird Hilfe nur aufgeklappt, wo ein entsprechendes Element existiert.

### Reproduzierbare Befehle

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
for test in tests/test_*_ui.js; do deno run --allow-read=static "$test" || exit; done
PYTHONPATH=/tmp/onair-browser-test-deps .venv/bin/python tests/browser_map_selection.py
PYTHONPATH=/tmp/onair-browser-test-deps .venv/bin/python tests/browser_trace_map.py
PYTHONPATH=/tmp/onair-browser-test-deps .venv/bin/python tests/browser_responsive.py
PYTHONPATH=/tmp/onair-browser-test-deps .venv/bin/python tests/browser_landscape.py
```

Für die Browserbefehle wird eine Python-Umgebung mit Playwright und das vorhandene
`/usr/bin/chromium` benötigt. Die temporäre Testinstallation überlebt keinen Neustart.
Screenshots der neuen Karte liegen nach dem Test unter
`/tmp/onair-map-selection-<Breite>x<Höhe>.png`; sie gehören nicht zum Repository.

## Bewusste Grenzen

- Der erste benötigte Linkabruf lädt weiterhin die vollständige kompakte Liste.
  Es gibt keine neue Einzelrepeater-API, Datenbankindizes oder Migrationen.
- Die Suche umfasst bekannte Repeater mit Vollidentitäten aus `nodes`, keine
  erfundenen Geräte für unaufgelöste Kurz-Hashes. Nicht kartierbare Kandidaten werden
  erklärt, aber nicht an eine geschätzte Position gesetzt.
- Geografische Entfernung begrenzt die Linkanzeige nicht. Vorhandene Regeln zu
  eindeutiger Identität, Positionsverfügbarkeit und Inaktivität bleiben bestehen.
- Die Expertenansicht kann weiterhin viele Geometrien erzeugen. Clustering und
  neue Kartenbibliotheken sind ausdrücklich nicht Bestandteil dieser Etappe.
- Die Prüfung nutzt synthetische Empfangsdaten und lokale Browser, keine Messung
  unter Produktionslast oder auf einem physischen Smartphone.

Keine produktive Bereitstellung vorgenommen.
