# TRACE-Ansicht 2.0 – Messvorgänge statt Einzelpakete

## Ergebnis und Umfang

**Map → TRACEs** zeigt Messgruppen als Haupteinträge. Zehn Fortschrittsstände
derselben fünfgliedrigen Messung erscheinen als ein Eintrag. Ein Klick öffnet
oberhalb der Empfangstabelle die Zusammenfassung und lädt einen repräsentativen
Einzelempfang für die bestehende Karte. Keine neuen Tabs oder Accordions.

Die drei Prioritäten sind umgesetzt: Gruppenhauptliste und Ergebnis zuerst,
repräsentativer Einzelempfang mit kompakter Empfangstabelle sowie Erhalt von
Kartenvergleich und Navigationskontext. Der bereits gruppierte separate
**TRACE**-Tab mit aggregiertem Verlauf bleibt in seiner Darstellung unverändert.

## Bestandsaufnahme und Gruppierung

onair_trace.py gruppierte bereits nach Tag, Auth-Code, Scope, Flags und
vollständiger Route, in einem festen Fenster von 60 Sekunden ab dem ersten
Empfang. Die Karte verwendete dagegen eine begrenzte Liste einzelner Pakete.
Der neue Gruppenmodus verwendet ausschließlich trace_sessions; es gibt keine
zweite Gruppierungslogik im Browser.

Eine andere Route, ein anderer Auth-Code, Tag oder Scope erzeugt eine andere
Gruppe. Wiederholte Routen-Hops bleiben in Reihenfolge erhalten. Diese passive
zeitliche Korrelation beweist nicht, dass alle Pakete tatsächlich demselben
Messvorgang angehören. Zeitraum- und Bestandsgrenzen können Gruppen abschneiden;
die Oberfläche weist darauf hin. Bei erreichtem 5000er-Limit erscheint ein
zusätzlicher Begrenzungshinweis.

Node-Auflösung und historische Positionsermittlung bleiben unverändert.
Unbekannte und mehrdeutige Hops werden nicht geografisch ergänzt.

## Ergebnisdarstellung und Einzelempfang

Gruppeneinträge zeigen unmittelbar Zeitpunkt, Tag, kompakte Route, Empfangs-
und Observerzahl, beste SNR-Abdeckung eines Einzelpakets, gemessenes
Gruppenminimum, unaufgelöste/mehrdeutige Hops sowie Scope, Auth-Code und Flags.

Die Vorauswahl erfolgt deterministisch:

1. Größte Anzahl tatsächlich enthaltener SNR-Messwerte.
2. Bei Gleichstand neuester Empfangszeitpunkt.
3. Danach höchste Empfangs-ID.

representative_id wird serverseitig bestimmt. Für die Karte wird weiterhin
/api/map-traces/{id} geladen. Die SNR-Werte dieser Antwort gehören nur zu diesem
Empfang. Gruppenminima/-maxima werden niemals als vollständig gemessene
Einzelroute gezeichnet. Die Zusammenfassung kennzeichnet Gruppenminimum und
Observerzahl als aggregiert und benennt den empfohlenen Einzelempfang.

Unterhalb stehen die bestehenden Karten-Auswertungskarten und dann die
Empfangstabelle: ID/Zeit, Observer einschließlich bekannter ID, SNR-Abdeckung,
gemessenes Minimum und Kartenwahl. Die Tabelle zeigt höchstens 50 Empfänge pro
Seite. Wechsel ihrer Seiten benötigen keine Anfrage.

Die Zusammenfassung steht über der Empfangsliste und wird bei Auswahl in den
sichtbaren Bereich gescrollt. Ein Button führt direkt zur vorhandenen Karte.
Die zuletzt gewählte Gruppe ist markiert.

## Vergleich und Kontext

- Höchstens zwei Einzelbeobachtungen bleiben auswählbar.
- Beim Öffnen einer anderen Gruppe wird ihr repräsentativer Empfang ergänzt,
  sofern ein Vergleichsplatz frei ist. Eine volle Auswahl wird nicht still
  ersetzt; die Oberfläche fordert zum Abwählen auf.
- Blau/Orange steht an Detailkarten und Tabellenaktionen. Wie bisher rückt
  nach Entfernen der ersten Auswahl die verbleibende nach Blau.
- Filter-/Gruppenseitenwechsel und normale Kartenansichten erhalten gewählte
  Empfangsdetails. Die geöffnete Gruppenzusammenfassung darf deshalb auch dann
  stehen bleiben, wenn sie nicht mehr zur neuen Trefferliste gehört.
- Hin-/Rückweg-SNR, wiederholte Traversierungen, historische Positionen und
  Lücken bleiben im vorhandenen TRACE-Zeichenweg.
- Suchanfragen verwenden weiterhin Versionsprüfung/AbortController gegen
  veraltete Antworten. Kartenbewegung löst keine TRACE-Abfrage aus.

## API, Begrenzung und Performance

Der bestehende Endpunkt wird um den optionalen Parameter grouped=true erweitert.
Start, Ende, erster/letzter Hop und Hopanzahl bleiben serverseitige Filter.
Ohne diesen Parameter bleiben bisherige Antwort und ID-basierte
Einzelempfangspagination erhalten. Der Detailendpunkt bleibt unverändert.

Im Gruppenmodus:

- Maximal 5000 neueste TRACE-Pakete im gewählten Zeitraum; ein zusätzlicher
  Datensatz erkennt Überschreitung. Dies entspricht der Größenordnung der
  vorhandenen TRACE-Auswertung. Die SQL-Abfrage kann zum Zeitfilter mehr
  Indexeinträge prüfen; keine konstante Abfragelaufzeit wird behauptet.
- Dieselbe Gruppierung wird einmal pro neuem Snapshot berechnet, anschließend
  werden die Hopfilter auf die Gruppen angewendet.
- Maximal 50 Gruppen pro Antwort. Der Parameter before ist **nur im
  Gruppenmodus** ein Offset in die sortierte Gruppenliste. Clients übernehmen
  den zurückgegebenen Cursor und mischen ihn nicht mit dem alten ID-Cursor.
- Ein Cache im Archive-Objekt hält höchstens zwei Snapshots für jeweils
  120 Sekunden. Schlüssel: Start, Ende und Hopfilter. Der vorhandene gemeinsame
  Lock schützt die Berechnung. Auswahlklicks berechnen keine Sessions neu.
- Gruppenseiten enthalten kompakte Empfangsmetadaten ihrer Gruppen, insgesamt
  begrenzt auf den 5000er-Snapshot. Nur 50 Tabellenzeilen werden gleichzeitig
  gezeichnet; dafür werden keine Rohpakete oder SNR-Arrays aller Empfänge geladen.
- Bestehende historische Positionscaches werden weiterverwendet.
- Empfangslisten werden nur bei include_packets=True ausgegeben; alte
  Analyse- und Detailantworten bekommen keine zusätzlichen langen Listen.
- Keine neuen Datenbankindizes, Migrationen, Bibliotheken oder Änderungen an
  Decoder, Funkpaketverarbeitung oder produktiven Daten.

## Geänderte Dateien

Die Liste umfasst auch den während der Arbeit übernommenen Zwischenstand
5f344c1, nicht nur die abschließenden uncommitteten Änderungen.

| Datei | Änderung |
|---|---|
| [onair_trace.py](../onair_trace.py) | Einzelmetadaten, deterministischer Repräsentant, sichtbare Auth-/Flags-Merkmale; Gruppenschlüssel unverändert. |
| [onair_trace_map.py](../onair_trace_map.py) | Begrenzter Gruppensnapshot und Gruppenpagination. |
| [onair_archive.py](../onair_archive.py) | Zwei Snapshot-Cacheplätze, 120 Sekunden, vorhandener Lock. |
| [onair_web.py](../onair_web.py) | Optionaler Parameter grouped; alte Aufrufe bleiben kompatibel. |
| [static/trace-map.js](../static/trace-map.js) | Gruppenhauptliste, Zusammenfassung, Empfangstabelle, Vorauswahl und Kontexterhalt. SNR-Zeichenlogik unverändert. |
| [static/index.html](../static/index.html) | Ergebnis und Details vor Empfangs-/Gruppenlisten; Gruppierungsgrenzen sichtbar. |
| [static/style.css](../static/style.css) | Umbrechende Gruppenbuttons, Auswahlmarkierung und mobile Empfangstabelle. |
| [tests/test_trace_map.py](../tests/test_trace_map.py) | Fortschrittsstände, keine künstlichen Messwerte, Repräsentant, Gruppenlimits, Pagination, Cache. |
| [tests/browser_trace_map.py](../tests/browser_trace_map.py) | Gruppenablauf, Vergleich, Filtererhalt, Empfangspagination, Desktop/Mobil/Querformat. |
| [README.md](../README.md), dieses Dokument | Bedienung, API-Erweiterung und Grenzen. |

## Testergebnisse

Offline, mit temporären Testdatenbanken und simulierten Browserantworten:

- **137 Python-Tests bestanden**, einschließlich bestehender Gruppen-Trennung
  nach Tag/Auth/Route/Scope/Zeitfenster, Mehrdeutigkeit, Hin-/Rückweg und
  historischer Positionsregeln.
- **Alle 16 JavaScript-Testskripte bestanden**, einschließlich TRACE,
  Discovery, MeshLive, Replay und Nachbaransicht.
- **TRACE-Browser:** bestehender Zwei-Routen-Vergleich mit acht SNR-Werten und
  fehlenden historischen Positionen; zusätzlich eine Gruppe aus zehn
  Fortschrittsständen, automatische Auswahl von Empfang #10 mit 5/5 SNR,
  zwei Observer, Einzelwahl und abgewiesene dritte Vergleichsauswahl.
- Gruppenablauf auf **1280×900, 390×844 und 844×390**. Kein seitlicher Überlauf;
  Zusammenfassung oberhalb der Empfangstabelle.
- Empfangstabelle mit **61 Einträgen**: Seiten 50/11, ohne zusätzliche Anfrage;
  Filterwechsel behält die vorhandene Kartenwahl.
- Backendpagination mit **120 Gruppen** ohne doppelte Gruppen-IDs; 5000er-Limit
  und Wiederverwendung des Snapshots über mehrere Seiten geprüft.
- **MeshLive und Replay:** bestehende Browserregressionen bestanden.
- **Responsive:** alle 14 Tabs auf neun Bildschirmgrößen; Querformat zusätzlich
  mit Rotation, Safe-Area, Scrollen und Größenprüfung beider Karten.
- git diff --check: keine Whitespacefehler.

Reproduktion: Python unittest discover mit tests/test_*.py, alle
tests/test_*_ui.js mit Deno und Leserechten für static sowie die Browserprogramme
browser_trace_map.py, browser_responsive.py, browser_landscape.py,
browser_meshlive.py und browser_replay.py.

Playwright wird über PYTHONPATH=/tmp/onair-browser-test-deps aus der vorhandenen
temporären Testinstallation geladen, Chromium lokal gestartet.
Screenshots: /tmp/onair-trace-v2-<Breite>.png.
Keine produktive Verbindung und kein Test auf physischer Smartphone-Hardware.

## Einschränkungen und mögliche Folgearbeiten

- Der Gruppenmodus durchsucht pro Zeitraum nur die neuesten 5000 Empfänge.
  Für ältere Messungen einen engeren benutzerdefinierten Zeitraum wählen.
  Die alte Einzelempfangs-API bleibt für bestehende Clients verfügbar.
- Nach Cacheablauf/-verdrängung wird bei erneuter Seitenanforderung ein Snapshot
  neu berechnet. Nachträglich eingefügte Archivdaten können Seiten verschieben;
  es gibt keinen langfristigen Snapshot-Token.
- Eine sehr große Gruppe kann bis zu 5000 kompakte Empfangsmetadaten enthalten.
  Eine separate serverseitige Empfangsseiten-API wäre eine spätere Optimierung;
  derzeit sind Übertragung und Browser-DOM begrenzt.
- Die eigenständige TRACE-Chronik behält ihre vorhandene Darstellung und
  aggregierten Verlaufsdiagramme. Der Umbau betrifft die Kartenansicht.
- Keine Produktionslastmessung; vorhandene SQL-Zeitfilter können bei großen
  Archiven Arbeit verursachen. Kein neuer Index ohne nachgewiesenen Bedarf.

Keine unvollständige Teilimplementierung zurückgelassen. Keine produktive Bereitstellung.
