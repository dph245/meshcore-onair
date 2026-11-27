# Historische TRACE-Linkstrecken

Die TRACE-Ansicht startet mit der Linkübersicht. Im selben Leaflet-Container
bleibt der Vergleich einzelner Empfänge unter „Messgruppen & Karte“
verfügbar. Die Chronik mit Routenverlauf behält ihren bisherigen,
zeitlich begrenzten Datenpfad. Die Linkübersicht arbeitet auf der
vollständigen TRACE-Projektion des Archivs.

Die Übersicht startet mit dem gesamten Bestand und allen Spreading
Factors. Wählbar sind außerdem 24 Stunden, 7 und 30 Tage und ein fester
Von-/Bis-Zeitraum. Der SF-Filter verwendet die historisch zugeordneten
Observer-Profile. Messwerte ohne bekannte SF-Zuordnung lassen sich
über „Unbekannt“ auswählen. Weitere SF erscheinen, sobald sie im
geladenen Zeitraum vorkommen.

Jede geografisch eindeutig auflösbare Verbindung im Filter erscheint
als Canvas-Linie. Zwei Repeater mit derselben belegten Position
erscheinen als Punkt. Die Geometrie stammt vom jüngsten kartierbaren
Messwert im Filter. Für die Linienfarbe gilt der kleinere der beiden
Richtungswerte. Unter −2 dB ist die Linie rot, von −2 bis 0 dB orange
und über 0 dB grün. Liegt nur ein Richtungswert vor, ist die Linie
gestrichelt und übernimmt dessen Farbe. Die Schwellen entsprechen
der SNR-Anzeige im Live-Tab.

Der Tooltip zeigt die SNR beider Richtungen. Der Median ist
voreingestellt. Letzter Messwert, Minimum und Maximum lassen sich
direkt in der Werkzeugleiste wählen. Beim Umschalten bleiben
Kartenausschnitt und Streckenauswahl erhalten. Ein Gedankenstrich
markiert einen fehlenden Richtungswert. Kompakte Kartenlabels sind
ab Zoom 11 verfügbar, vollständige ab Zoom 9. Beide sind
standardmäßig ausgeschaltet.

Klick oder Tippen auf eine Strecke hebt sie hervor und lädt ihren
Messverlauf für beide Richtungen im ausgewählten Zeitraum und SF.
Die Kurven enthalten dieselben geografisch belegten Messwerte, aus
denen die Richtungsstatistik der Karte berechnet wird. Pro korrelierter
TRACE, Richtung und exaktem Observer-Profil zählt bei wiederholtem Hop
der kleinste SNR-Wert. Bei „Alle SF“ fließen alle passenden Profile in
die jeweilige Richtungsstatistik ein. Die aufklappbaren Einzelmessungen
enthalten die gerichteten Hop-Werte mit den Empfangsbelegen und
gegebenenfalls dem Grund für den Ausschluss aus Karte und Diagramm.
Auf breiten Fenstern steht das einklappbare Detailpanel mit
verstellbarer Breite neben der Karte, auf schmalen darunter.
Der Browser speichert die Karten- und Panel-Einstellungen lokal.

## Initiale Kartenzeichnung

Beim TRACE-Tabwechsel macht `selectTab()` zuerst das Panel sichtbar.
`showTraceWorkspace()` öffnet die gemeinsame Leaflet-Karte und danach
aktiviert `TraceLinks.sync()` die Linkübersicht. Die erste API-Antwort
ändert Status und Analyselegende. Dadurch kann der Kartencontainer auch
nach seiner ersten Größenmessung noch kleiner werden.

In Chromium ließ sich der leere Canvas beim erneuten Öffnen auf Desktop
sowie im Hoch- und Querformat reproduzieren. Im Desktop-Lauf waren bei
785 × 455 Pixeln vier Polylinien mit projizierten Koordinaten registriert,
der sichtbare Canvas enthielt null gezeichnete Pixel. Beim Verlassen hatte
das Entfernen der Pfade noch einen Canvas-Zeichenframe vorgemerkt.
Leaflet 1.9.4 brach den Frame beim Entfernen des Renderers ab, behielt
aber dessen Kennung. Beim Wiederanhängen erzeugte derselbe Renderer einen
neuen Canvas, bevor die Pfade registriert waren. Der gespeicherte
Frame-Status blockierte die nächste Zeichenanforderung. Bei unveränderter
Containergröße löste `invalidateSize()` keinen `moveend` aus.
Eine Verschiebung um drei Pixel ließ Leaflet die Pfade neu zeichnen.

Beim regulären ersten Öffnen zeichnete Chromium die Verbindungen.
Ein separater Versuch mit temporär 0 × 0 Pixeln belegte, dass
`fitBounds()` bereits bei unbrauchbarer Größe lief. Auch bei einem
normalen ersten Aufruf konnte die Analyselegende das Layout zwischen
der letzten Größenmessung und der Bounds-Berechnung ändern.

Die Linkübersicht hält eine früh eintreffende Antwort bis zur Aktivierung
vor. Sie wendet zuerst Status, Filter und Legende an. Sobald der Container
eine nutzbare Größe hat, gleicht sie diese mit Leaflet ab und verwendet
`invalidateSize()` nur bei abweichenden Abmessungen. Die einmalige
Bounds-Berechnung erfolgt vor dem Zeichnen der Pfade. Der bestehende
`ResizeObserver` übernimmt spätere Layoutänderungen und gibt eine noch
ausstehende Zeichnung frei. `moveend` und `zoomend` aktualisieren weiterhin
Leaflets Darstellung und die sichtbaren Labels.

Beim erneuten Öffnen bindet die Linkübersicht dieselben Pfade, Marker
und Layergruppen an einen frischen Canvas-Renderer. Mittelpunkt und
Zoom bleiben bei Tab- und Größenwechseln erhalten. Das Wiederanhängen
nutzt die geladene Antwort. Geänderte Archivrevisionen und ältere
relative Zeitfenster verwenden den bestehenden Aktualisierungspfad.
Die Zeichnung benötigt keine zusätzlichen Timer oder Archivabfragen.

Der Chromium-Regressionstest liest für beide erwarteten Linien Pixel
in ihrer Strichfarbe im sichtbaren Kartenausschnitt. Er öffnet den Tab
per Tastatur und deckt frühe und verzögerte Antworten, Antworten im
Hintergrund, den zunächst größenlosen Container, wiederholte Tabwechsel,
die Detailpanelbreite und verschiedene Fensterformate ab. Er prüft die
Wiederverwendung der Pfade, eine einzige anfängliche Bounds-Berechnung
und genau einen Archivabruf je Testablauf.

Der Pixeltest schlug vor der Korrektur beim ersten erneuten Öffnen
fehl. Danach bestanden der Pixeltest, die Chromium-Läufe für
Einzelvergleich und responsive Ansichten, alle 19 Deno-Skripte
und 268 Python-Tests. Die Offline-Stichprobe mit 124 archivierten
Strecken benötigte 30,2 ms von der dekodierten Antwort bis zur
bestätigten Darstellung. Die Analysemoduswechsel lösten keinen
zusätzlichen Archivabruf aus.

## Netzqualitätsanalyse

Die folgenden Abschnitte dokumentieren die frühere Browseransicht
und die weiterhin verfügbaren ausführlichen API-Daten. Die damalige
Startansicht war „Linkqualität“. Die Werkzeugleiste enthielt außerdem
„Asymmetrie“, „Messabdeckung“ und „SF7-Reserveprognose“. Die anklickbare
Legende zählt kartierbare Paare vollständiger Repeater-IDs innerhalb des
gewählten Zeitraum- und Profilfilters. Jede Strecke zählt in einer
Kategorie. Die Zahlen bleiben beim Anklicken einer Kategorie als
Bezugsgröße stehen. „Alle Strecken“ setzt den Kategoriefilter und
„Nur Prüfbedarf“ zurück. Der Messbestand weist gerichtete Werte ohne
Geometrie sowie eindeutige TRACE mit gerichteten Werten im Profilfilter
und ohne jede kartierbare Strecke separat aus. Teilweise empfangene
TRACE, nicht dekodierbare Empfänge und TRACE ohne kartierbare Strecke
im gesamten Zeitraum bilden den Kontext für alle Profile.

Linienmuster, ausgeschriebene Kategorien und ein Hinweis auf fehlende
Richtungsdaten ergänzen die Farben. „Nur Prüfbedarf“ zeigt die unteren
Kategorien des aktiven Modus, offene Bewertungen und Strecken mit
fehlenden Richtungsdaten. Die Auswahlliste sortiert nach kleinster
nomineller Reserve, größter vergleichbarer Asymmetrie, geringster
Abdeckung, kleinster SF7-Reserve, jüngster Messung oder kürzester
Luftlinie. Fehlende Zahlen stehen beim numerischen Sortieren zuletzt.
Bei Abdeckung folgen innerhalb einer Kategorie zuerst die Strecken
mit der geringsten Zahl in der schwächer erfassten Richtung. Dabei
zählt eine Richtung ohne Messung als null Messungen. Liste und Karte
teilen die Auswahl. Beim Wechsel von Modus, Kategorie oder Auswahl
bleiben Kartenausschnitt und Zoom erhalten. Der Modus, die Sortierung,
„Nur Prüfbedarf“, Zeitraum, SF-Filter, SNR-Anzeige, Labelmodus und
Panel-Einstellungen werden lokal gespeichert.

### Stichprobe und Perzentile

Je vollständigem Repeater-Paar, Richtung und exakt zugeordnetem
Observer-Profil zählt eine korrelierte TRACE-ID einmal. Führen mehrere
Hops desselben TRACE in gleicher Richtung über dieselbe Strecke im
selben Profil, geht der kleinste SNR in die Statistik ein. Bei gleichem
SNR gilt der früheste Hop-Zeitpunkt, danach die Hop-Position. Der
Zeitpunkt des repräsentativen Werts gehört zur Stichprobe. Die
Einzelwertseite erhält jeden Hop und die zugehörigen Empfangsbelege.
Mehrere Observer desselben Funkereignisses erhöhen die Stichprobe
dadurch nicht. Passive Korrelation kann identische Wiederholungen
unter den weiter unten beschriebenen Bedingungen zusammenfassen.

P10, Median und P90 verwenden lineare Interpolation im sortierten
Viertel-dB-Histogramm. Für das Quantil $p$ liegt der nullbasierte Rang
bei $(n - 1) \times p$. Zwischen benachbarten Werten wird linear
interpoliert. Beispielsweise ergibt die Stichprobe 0 und 0,25 dB ein
P10 von 0,025 dB, einen Median von 0,125 dB und ein P90 von 0,225 dB.
Ein einzelner Wert liefert an jedem Rang denselben SNR. Fehlende
Richtungen haben den Wert `null`. Die Kartenstatistik verwendet
kartierbare Hops. Die Einzelwertseite führt auch Messwerte mit
eindeutigen Identitäten und gesperrten Standorten samt Ausschlussgrund.

### Nominelle Reserve und SF7-Schätzung

Die Referenzwerte und Schwellen stehen in `RULES` und werden mit der
Kartenaggregation ausgeliefert. Die Oberfläche zeigt dadurch die beim
Berechnen verwendeten Werte in der Expertenansicht.
[OnAir-Bewertungsregeln](../onair_trace_quality.py)

Für eine Einstufung braucht jede berücksichtigte Richtung mindestens
drei korrelierte TRACE mit demselben Profil. Von drei bis neun Werten
gilt der Median und der Befund ist vorläufig. Ab zehn Werten gilt das
konservativere P10. Die nominelle Reserve ergibt sich aus diesem
SNR-Kennwert abzüglich der Demodulationsreferenz. Werte ab 6 dB gelten
als gut, von 3 bis unter 6 dB als gering und unter 3 dB als sehr gering.
Ohne berechenbare Reserve bleibt die Strecke grau. Bei mehreren
Profilen bestimmt die kleinste berechenbare Reserve innerhalb eines
einzelnen Profils die Karte. Eine Bewertung auf Grund einer Richtung
wird gekennzeichnet, auch wenn die andere Richtung in einem anderen
Profil beobachtet wurde. Die Bewertung des maßgeblichen Profils und
die Werte aller Profile bleiben einzeln nachvollziehbar.

| Spreading Factor | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Nomineller Demodulator-SNR in dB | −2,5 | −5 | −7,5 | −10 | −12,5 | −15 | −17,5 | −20 |

Die Referenzen sind typische LoRa-Demodulatorwerte aus Tabelle 6-1 im
SX1261/SX1262-Datenblatt. Negative SNR-Werte können eine gute Reserve
ergeben. Die nominellen Werte und die OnAir-Kategorien treffen keine
Aussage über garantierte Empfangsgrenzen einer bestimmten Hardware.
[Semtech SX1261/SX1262-Datenblatt, Tabelle 6-1](https://media.digikey.com/pdf/Data%20Sheets/Semtech%20PDFs/SX1261-62_v1.2_Jun2019.pdf#page=38)

Die Prognose setzt ausschließlich einen SF8-SNR-Kennwert in
`SF8-SNR − (−7,5 dB)` ein. Für dieselbe Stichprobe liegt diese
Schätzung 2,5 dB unter der nominellen SF8-Reserve. Die Auswahl
„Alle Funkprofile“ erlaubt die Anzeige der SF8-Schätzung, weitere SF
fließen nicht in sie ein. Bei SF7-Filterung wird keine SF8-Schätzung
angezeigt. Beide Reservemodi und die Asymmetrie setzen gemeldete
Frequenz, Bandbreite, SF und Coding Rate voraus. Unbekannte,
widersprüchliche und zeitlich unsichere Zuweisungen bleiben aus diesen
Berechnungen ausgeschlossen. Vollständige, zuletzt gemeldete Profile
sind vorläufige Observer-Evidenz und werden als solche ausgewiesen.

Die SF7-Rechnung setzt für den Vergleich ansonsten gleichbleibende
Bedingungen voraus. Senderkonfiguration, Coding Rate auf dem Funkweg,
Chip, Firmware und Störeinflüsse können vom Modell abweichen. Die
Prognose beschreibt mögliche Reserven für beobachtete, erfolgreich
transportierte SF8-Werte. Zustellwahrscheinlichkeit, Ausfälle und die
tatsächliche SF7-Erreichbarkeit bleiben offen.

### Asymmetrie und Messabdeckung

Die Asymmetrie vergleicht Richtungen ausschließlich innerhalb desselben
vollständigen Observer-Profils. Die Zeitstempel werden in gemeinsame
UTC-Stunden eingeordnet. Ein Fenster zählt, wenn beide Richtungen
enthalten sind und das Verhältnis der Anzahlen höchstens 3 zu 1 beträgt.
Mindestens zwei solcher Fenster und insgesamt mindestens drei Werte je
Richtung sind erforderlich. Pro Fenster wird der SNR-Median der
Rückrichtung vom Median der Hinrichtung abgezogen. Der Median dieser
signierten Differenzen gewichtet die Zeitfenster gleich. Sein Betrag
bestimmt die Kategorie. Bis 3 dB gelten die Richtungen als ähnlich,
über 3 bis einschließlich 6 dB als merklich unterschiedlich, darüber
als stark unterschiedlich. Bei mehreren Profilen bestimmt der größte
vergleichbare Betrag die Karte. Ein wechselnder Richtungsunterschied
kann sich im Median ausgleichen. Gleiche Stunden sind eine Konvention
für zeitliche Nähe. Die beiden Richtungen können unterschiedliche
Streckenbetreiber, Geräte oder Umgebungsbedingungen haben.

Die Abdeckung zählt pro Richtung jeden TRACE einmal über alle im Filter
enthaltenen Profile. Liegen innerhalb eines TRACE für dieselbe Richtung
mehrere Profile vor, zählt er einmal mit der Qualität „Mehrere Profile“.
Neben der Anzahl gehen verschiedene UTC-Kalendertage, Netto-Zeitspanne,
das Alter der letzten Messung am gewählten Fensterende und der Anteil
vollständig zugeordneter Profile in die Bewertung ein. Für die Karte
gilt die schwächer erfasste Richtung.

| Einstufung | TRACE je Richtung | UTC-Tage | Zeitspanne ab | Letzte Messung höchstens | Profilzuordnung ab |
| --- | ---: | ---: | ---: | ---: | ---: |
| Breit vermessen | 10 | 3 | 48 h | 7 Tage alt | 80 % |
| Teilweise vermessen | 3 | 2 | 24 h | 30 Tage alt | 50 % |
| Dünn vermessen | übrige Fälle einschließlich einseitiger Abdeckung | | | | |

### Prüfung im Detailpanel

Das Panel erklärt den aktiven Befund anhand der Daten. Die Messübersicht
zeigt Luftlinie und Standortbeleg, Repeater-IDs, Richtung, Stichprobe,
Zeitraum, SNR, Reserve und Profilqualität. Die Expertenansicht ergänzt
Perzentile, exakte Profilparameter, Prüfregeln und Präfixbreiten.
Das Verteilungsdiagramm zeichnet die bereits geladenen fünf Quantile
des jeweiligen Profils erst beim Öffnen. Die Zeitdarstellung wird
erst nach dem Laden einer Einzelwertseite auf Anforderung gezeichnet.
Sie zeigt die Hop-Punkte der aktuell geladenen Seite getrennt nach
Richtung und gewähltem exaktem Profil. Empfangsbelege, Quell- und
OnAir-Zeit, Observer-Identitäten und Rohpaket-IDs sind aus der
Einzelwertseite und ihren aufklappbaren TRACE-Referenzen erreichbar.

Die API liefert die Paare mit sortierten vollständigen Keys, getrennten
Richtungen und Befunden je Modus. Diese Struktur eignet sich als
Ausgangspunkt für einen Graphen der beobachteten Topologie. Die
Reservekategorien bewerten Funkbeobachtungen. Aussagen etwa über
Brückenkanten, Erreichbarkeit oder isolierte Regionen brauchen eine
gesonderte Graphanalyse und geeignete Messdaten.

Die Karte behält ihre Filter und Layer bei archivbedingten
Aktualisierungen. Snapshots enthalten die TRACE-Revision vollständig.
Der WebSocket sendet die Revision nach Änderungen an der Projektion,
an relevanten Archivdaten oder beim Backfill. Die aktive Karte bündelt
solche Hinweise auf höchstens eine Hintergrundabfrage pro zehn
Sekunden. Beim Verlassen der Ansicht werden laufende Anfragen
abgebrochen und Canvas und Zoom-Beschriftungen ausgehängt. Die
Layerobjekte bleiben zum Wiederverwenden im Speicher.

## Paketformat und Zuordnung der Richtung

MeshCore legt nach dem äußeren Header den SNR-Fortschritt ab. Jedes
Byte entspricht einem signierten Viertel-dB-Wert. Die Payload beginnt
mit je vier Bytes Tag und Auth-Code in Little Endian, gefolgt von
einem Flag-Byte und der vollständigen angefragten Route. Die unteren
zwei Bits der Flags kodieren die Breite als 1, 2, 4 oder 8 Bytes.
Die beobachteten 8-Byte-Frames verarbeitet dieselbe Logik. Reservierte
Flags und andere nicht interpretierbare Frames bleiben über Rohpaket
und Empfangsstatus im Archiv. Der allgemeine Path-Hash im äußeren
Header und die TRACE-Präfixbreite sind unterschiedliche Felder.
[MeshCore-Paketformat](https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md)

`snrs[i]` gehört zum Empfänger `route[i]`. Ab `i = 1` ist die
unmittelbar vorherige Adresse `route[i-1]` die gemessene Gegenstelle.
Der Wert bei `i = 0` bleibt am ersten Hop erhalten. Das Funkpaket
weist die Identität des auslösenden Companion und dessen Standort
nicht verlässlich aus. Der serielle Companion-Endwert liegt außerhalb
des beobachteten TRACE-Pakets. Der Observer-RSSI und Observer-SNR
gehören ausschließlich zum jeweiligen MQTT-Empfang.
[Mesh::onRecvPacket und Mesh::sendDirect](https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp)
[MyMesh::onTraceRecv](https://github.com/meshcore-dev/MeshCore/blob/main/examples/companion_radio/MyMesh.cpp)

Der auf dem Funkweg beobachtete Rückweg steckt in der Routenfolge.
Die Projektion erhält jede Position einschließlich wiederholter
Repeater und jedes gemessene Auftreten eines gerichteten Paars.
Asymmetrische und unvollständige Routen folgen derselben Regel.
„Vollständig“ bedeutet, dass für alle adressierten Hops ein
transportierter SNR vorliegt. An einem fehlenden oder mehrdeutigen
Hop endet die Geometrie. Nachfolgende belegte Nachbarhops können
eine eigene Strecke bilden.

## Schema 18 und Korrelation

- `trace_measurement` speichert eine stabile interne ID, die
  unveränderte Wire-Identität, Präfixbreite, Route, längsten konsistenten
  SNR-Fortschritt und erste und letzte Ereigniszeit. Die ID ist die
  Paket-ID der zuerst indexierten Beobachtung dieser Gruppe.
- `trace_observation` verweist für jeden archivierten TRACE-Empfang
  auf das Rohpaket. Sie hält Observer-ID, Quellzeit, OnAir-Empfangszeit,
  Ereigniszeit, SNR-Abdeckung, Retain-Kennzeichen, Korrelationsgrund
  und die Referenz eines erkannten Duplikats. Die beim Indexieren
  ermittelte Profilqualität und der Schema-17-Zeitschlüssel bleiben
  am Empfang erhalten. Das Profil selbst steht in der vorhandenen
  Historie. Unlesbare Einträge haben eine Rohpaket-ID und keinen
  Messungsbezug.
- `trace_sample` enthält je Messung und empfangendem Hop ein Paar
  vollständiger beobachteter Präfixe, den signierten Viertel-dB-Wert
  und die früheste Zeit der zugehörigen Beobachtung. Indizes decken
  Zeitfenster und gerichtete Präfixpaare ab. Funkprofilzeitreihen
  werden gesammelt über die Schema-17-Indizes für die beteiligten
  Observer gelesen. Median und weitere Statistiken entstehen
  serverseitig aus diskreten Viertel-dB-Histogrammen.
- `trace_backfill` hält Obergrenze, Cursor, Zahl gelesener TRACE-Zeilen
  und Abschlussstatus. Der Archivschreiber nutzt `packets_kind_id`
  und führt höchstens 100 Altzeilen je Transaktion nach. Live-Empfänge
  haben Vorrang. Projektion und Cursor werden gemeinsam übernommen.
  Bei Neustart setzt die Verarbeitung am persistierten Cursor an.
  Die Paket-ID macht Wiederholungen idempotent. Der Backfill liest die
  archivierten Rohpakete und schreibt die Projektion.

Wire-Identität umfasst Routingtyp, Version, die rohen Transportcodes
sowie Tag, Auth-Code, Flags und Route. Eine Gruppe umfasst maximal
60 Sekunden. Korrelation verlangt einen identischen gemeinsamen
SNR-Präfix. Beobachtungen verschiedener Observer desselben Fortschritts
müssen innerhalb von drei Sekunden liegen. Verschiedene Fortschritte
können korrelieren, solange bekannte Zeitreihen desselben Observers
und die vorhandene Abdeckung dazu passen. Zeitumkehrungen in der
nachrichtenbasierten Reihenfolge werden mit plausibler Quellzeit
aufgelöst. Ein neues Vorkommen desselben Fortschritts beim selben
Observer bleibt separat. Ein gleiches hochauflösendes Zeitmerkmal
beim selben Observer und derselbe Fortschritt mit unveränderten
SNR-Bytes kennzeichnen eine Wiederzustellung. Der Rohbeleg bleibt auch
in diesem Fall referenziert. Abweichende SNR-Bytes und mehrere
plausible Gruppen erzeugen separate, entsprechend gekennzeichnete
Messungen. Ein identischer Wiederholungsversuch, den ausschließlich
verschiedene Observer im Korrelationsfenster mit identischen SNR-Daten
beobachten, lässt sich passiv nicht immer trennen.

Die Ereigniszeit ist die plausible Observer-Quellzeit, ersatzweise
der OnAir-Empfang. Alte Paketzeilen enthalten gewöhnlich nur eine
Uhrzeitanzeige ohne belastbare Datumsangabe. Retained Empfänge ohne
Quellzeit bleiben in einer eigenen Gruppe mit unbekanntem Profil.
Fehlen in Live-Paketen vollständige IDs, kann das übliche MQTT-Topic
mit Public Key die Identität belegen. Ein Widerspruch zwischen Topic
und Payload lässt die Observer-ID für diese Zuordnung offen.

Präfixauflösung erfolgt bei der Abfrage gegen bekannte vollständige
Identitäten. Kürzere Präfixe behalten ihre Länge. Eindeutige
Vier-Byte-Präfixe können eine Kollision der ersten drei Bytes umgehen.
Mehrdeutige, unbekannte und nicht geografisch zuordenbare Hops bleiben
mit Status auswertbar. Signierte ADVERTs können die Identität
nachträglich auflösen. Der Präfixschutz gilt unabhängig von den
verfügbaren Standortbelegen.

## Zeitbezogene Standortvalidierung

Die Linkübersicht, der Einzelvergleich und die Messwertdetails
bewerten beide Endpunkte einer Richtung zur Ereigniszeit des
empfangenden Hops. Bei korrelierten TRACE-Empfängen ist das der
Zeitpunkt des projizierten Hop-Werts. Außerhalb der Projektion
verwendet der Einzelvergleich die Observer-Quellzeit und ersatzweise
den OnAir-Empfang. Identitätsstatus und Standortstatus stehen in
getrennten Feldern (`state` und `location_issue`).

Für jeden vollständigen Key werden gültig signierte ADVERTs mit
Koordinaten nach OnAir-Empfang und Archiv-ID geordnet. Der
eingebettete ADVERT-Zeitstempel dient beim Vergleich der Belege
und zur Erkennung gleicher Aussendungszeiten. Die Uhr des Senders
kann zurückgesetzt oder versetzt sein. Für den Beginn einer
Positionsphase zählt deshalb die Empfangszeit. Die Routenmeldung
selbst enthält keine Standortangabe.

| Belege | Standortentscheidung |
| --- | --- |
| Keine Koordinaten oder `(0, 0)` | Kein Standortbeleg. Eine vorhandene Position bleibt gültig. |
| Erster gültiger Standort | Ab seinem ersten Empfang verfügbar. |
| Abweichungen innerhalb der Toleranz | Derselbe Standort. Kartenpunkt bleibt der erste Punkt seiner Phase. |
| Abweichender Punkt oberhalb der Toleranz | Ab seinem Empfang ausblenden. Zeitnah empfangene Gegenbelege und deutlich abweichende Koordinaten desselben ADVERT-Zeitstempels gelten als Konflikt. Ein einzelner abweichender Beleg nach längerer Ruhe gilt als unbestätigter Standortwechsel. |
| Wiederholt wechselnde Standorte desselben Keys | Jeder Gegenbeleg beginnt die Bestätigung erneut. Die Position bleibt gesperrt, solange widersprüchliche Belege weiter eintreffen. |
| Eindeutige Folgemeldungen | Freigabe ab einer weiteren gültigen Meldung, wenn der Standort seit dem letzten Gegenbeleg durch mindestens zwei erstmals empfangene, steigende ADVERT-Zeitstempel belegt ist und mindestens sechs Stunden ohne Gegenbeleg verstrichen sind. |

`ONAIR_TRACE_POSITION_TOLERANCE_M` ist eine endliche,
nichtnegative Entfernung in Metern. Der Standardwert **25 m**
deckt GPS-Rundung und leichte Positionsabweichungen ab. Die
Haversine-Distanz wird zum Kartenpunkt der jeweiligen Phase
gemessen. Beim selben ADVERT-Zeitstempel werden auch die
Varianten untereinander auf Gegenbelege geprüft. Ein mehrfach
empfangenes ADVERT mit demselben Zeitstempel und denselben
Koordinaten zählt einmal zur Bestätigung. Ein erneut empfangener
abweichender Beleg kann einen Standort weiter sperren.
Die sechsstündige Ruhezeit lässt bei üblichen dreistündigen
Repeater-Intervallen Raum für zwei entgegengesetzte Meldungen.

Nach einer Freigabe bleiben Messungen aus dem Konfliktintervall
ausgeblendet und werden als historischer Standortkonflikt
bezeichnet. Frühere eindeutige Phasen behalten ihre eigenen
Positionen. Ein Zeitfenster über mehrere Phasen zeigt pro
Repeater-Paar die Geometrie seines neuesten kartierbaren Werts
im Fenster. Die Einzelwerte behalten ihre jeweilige Messzeit.
Ein engeres Zeitfenster kann die frühere Geometrie darstellen.
Unbeobachtete Geräte lassen sich passiv nicht ausschließen.
Bei sehr seltenen oder verspäteten ADVERTs bleibt der genaue
Zeitpunkt eines physischen Standortwechsels offen.

Eine neue Standortentscheidung benötigt keine Migration und
ändert keine Rohpakete, SNR-Werte oder Hop-Projektionen. Der
erste Abruf nutzt `packets_advert_key_received` mit einer
Liste der beteiligten vollständigen Keys. Die Ergebnisse werden
für bis zu 256 Keys pro Archiv zwischengespeichert. Bei neuen
Paketen sucht `packets_kind_id` im hinzugekommenen ID-Bereich
nach ADVERTs. Nur Zeitachsen mit neuen Standortdaten werden neu
berechnet. Ältere Archivkorrekturen invalidieren den Cache über
die bestehende Positionsrevision. Bei großen ID-Sprüngen lädt
der nächste Abruf die benötigten Keys erneut. Zoomen und
Analysemoduswechsel verursachen keine Positionsabfrage.

### Abnahme der Standortvalidierung

C5355091 liefert am 27.11.2026 in der SQLite-Lesestichprobe
vier aufgelöste Repeater und drei bidirektionale Strecken mit
den sechs unveränderten [Richtungswerten](#diagnose-für-trace-c5355091-am-27112026).
Die automatisierte Regression verwendet die Originalbytes des
vollständigen Empfangs und gekürzte Zeitreihen der zugehörigen
Standortvarianten in einer temporären SQLite-Datei. Weitere Tests
decken fehlende Positionen, Toleranz, identische Zeitstempel,
Mehrfachempfänge, alternative Standorte, Standortwechsel, spätere
Bestätigung und den gemeinsamen Messzeitpunkt beider Link-Endpunkte
ab. Die Funkfeuer-Präfixe `dd`, `dd4c` und `dd4c42` bleiben
im realen Archiv mehrdeutig. Der präzise Key `dd4c42a1…` hat am
Referenzzeitpunkt weiterhin keinen kartierbaren Standort.

Der Offline-Benchmark las 2.657.257 Paketzeilen und 8.172
TRACE-Empfänge. Der temporäre TRACE-Backfill dauerte 10,14 s.
Im Gesamtfenster ergab die Abfrage 124 Strecken und 1.246
kartierbare Richtungswerte. Der Median lag bei 27,21 ms für die
Aggregation und bei 1,71 ms für den SQL-Lesezugriff auf
`trace_sample`. `EXPLAIN QUERY PLAN` bestätigt Bereichssuchen
über beide ADVERT-Zugriffe. Im Versionsvergleich auf derselben
Lesetransaktion dauerte das ganze Archivfenster unter `c9f69e0`
93,31 ms im Median, mit gefülltem Cache 28,46 ms. Ein direkt
als erster Abruf gewähltes Gesamtfenster dauerte 251,35 ms,
weil es die Belege für alle beteiligten Keys erstmals lädt.

Der frühere Gzip-Test hing bereits beim ersten Aufruf ohne
Kompression. In der Sandbox scheitert das Schreiben in das
Socket-Paar der asyncio-Ereignisschleife mit `EPERM`. Dadurch
wird die Schleife nach Abschluss eines FastAPI-Workerthreads
nicht aufgeweckt. Der Gzip-Test prüft jetzt drei reale
HTTP-Anfragen an Uvicorn auf Loopback mit einer temporären
Archivdatenbank und deaktiviertem MQTT-Lifespan. Er vergleicht
die dekomprimierten Bytes mit der unkomprimierten Antwort und
prüft die Aushandlung mit und ohne Gzip-Freigabe.
Die vollständige Python-Suite bestand mit 268 Tests bei erlaubten
lokalen Sockets. Alle 19 Deno-Skripte und beide Chromium-Prüfungen
für TRACE-Karten bestanden.

## Funkprofile und Grenzen der Beobachtung

Das Schema-17-Profil wird je Observer und Ereigniszeit nach denselben
Regeln wie `Archive.observer_radio_at` eingeordnet. Zusätzlich zur
Einstufung beim Indexieren wertet die Abfrage die Profilhistorie
erneut aus. Damit wirken später bekannt gewordene Übergänge und
Konflikte auf die Auswertung. Für jeden gerichteten Wert zählen
ausschließlich Beobachtungen, die ihn tatsächlich transportieren.
Bekannte, widerspruchsfreie Werte können ein eindeutiges Profil
liefern. Dazu muss eine tatsächliche Profilmeldung alle verwendeten
Parameter enthalten. Konkurrierende Profile, erkannte Übergänge
und fehlende SF-Evidenz bleiben unter „Unbekannt“. Frequenz, Bandbreite,
SF, CR und vorhandene weitere Funkparameter bleiben getrennt
gruppierbar. „Bestätigt“ bezeichnet eine gemeldete
Observer-Konfiguration zu ihrem Quellenzeitpunkt. „Zuletzt gemeldet“
bezeichnet den letzten verfügbaren Beobachtungsstand.
[Schema-17-Zeitsemantik](observer-radio.md#schema-17-und-zeitliche-zuordnung)

Die Profilzuordnung beschreibt die Einstellungen der empfangenden
Observer. Die Konfiguration einzelner Sender am TRACE-Pfad und die
Coding Rate auf dem Funkweg bleiben offen. Ausbleibende Beobachtungen
lassen den tatsächlichen Funkverlauf offen. Der Vergleich von SF7
und SF8 und die Auswertung einer Messkampagne folgen separat.

`GET /api/trace-links` liefert je Zeitraum und SF aggregierte
Verbindungen. `start` ist einschließlich, `end` ausschließlich.
Der Browser ruft die Übersicht mit `compact=true` ab. Je Strecke
enthält `snr` für die beiden Richtungen Anzahl, letzten Messwert,
Median, Minimum und Maximum. Die ausführliche API-Antwort führt
die bisherigen profilgetrennten Statistiken und Analysedaten.
Bei explizit akzeptiertem Gzip werden Antworten ab 1.024 Bytes
komprimiert.

Zwei sortierte vollständige Public Keys als `a` und `b` laden
seitenweise bis zu 50 gerichtete Hop-Werte einer Verbindung.
Die erste Seite mit `compact=true` liefert zusätzlich in `history`
beide Richtungen als Folge von Ereigniszeit und SNR in dB für den
gewählten Zeitraum. Die Einzelwerte zeigen Richtung, Funkprofil
und Rohpaket-Referenzen. Die beteiligten bekannten Observer-IDs
beziehen sich auf den gesamten gefilterten Bestand dieser Strecke.
`GET /api/trace-measurements/{id}` liefert die geordnete Route,
alle Empfangsbelege, RSSI und SNR je Observer und die Zuordnungsgründe.

## Realer 4-Byte-TRACE

Archivpaket **#2604758**, Projektion **#2604741**. Header `26 07`
steht für DIRECT-TRACE mit sieben SNR-Bytes. Der Fortschritt lautet
`2c 31 1e 29 29 25 31`. In der Payload folgen
`82 56 cb a8 50 8b df 26 02` mit Tag `a8cb5682`, Auth-Code
`26df8b50` und Flag `02` für 4-Byte-Präfixe.

| Gemessene Richtung | SNR-Byte | dB |
| --- | --- | ---: |
| unbekannte Quelle → `77730034` | `2c` | +11,00 |
| `77730034` → `747400e7` | `31` | +12,25 |
| `747400e7` → `6f33a924` | `1e` | +7,50 |
| `6f33a924` → `bf92b989` | `29` | +10,25 |
| `bf92b989` → `6f33a924` | `29` | +10,25 |
| `6f33a924` → `747400e7` | `25` | +9,25 |
| `747400e7` → `77730034` | `31` | +12,25 |

Vier verschiedene vollständige Keys wurden aufgelöst. Die
archivweite Standortprüfung aus Sprint 2 blendete wegen früherer
Gegenbelege `77730034` und `bf92b989` aus. Sie zeigte daher aus
dieser Messung nur `747400e7` ↔ `6f33a924`. Die Projektion
enthält alle sechs gerichteten Werte und den ersten Empfangswert.

### Diagnose für TRACE `C5355091` am 27.11.2026

Die korrelierte Messung hat die ID **2654806**. Der vollständige
Empfang **2654832** enthält sieben SNR-Bytes. Die sechs gerichteten
Repeaterwerte stammen aus der Observer-Quellzeit von 00:10:02 bis
00:10:10 Uhr (Europe/Berlin).

| Strecke | Hin | Zurück |
| --- | ---: | ---: |
| WF-Rodeland → WF-Ost | +11,75 dB | +12,75 dB |
| WF-Ost → WF-Nord-Ost | +9,50 dB | +10,75 dB |
| WF-Nord-Ost → WF-Mitte | +10,50 dB | +10,50 dB |

Die Rohbytes bestätigen gültige Signaturen und folgende ADVERT-Varianten.
Alle Zeiten in der Tabelle sind Ortszeiten. Die Empfangszeiten stammen
aus `packets.received`, dem von OnAir gespeicherten MQTT-Empfang.
Für den Observer steht im Paket-JSON nur eine Uhrzeit ohne Datum.
Einen separaten SQLite-Commitzeitpunkt speichert das Archiv nicht.
Die Paket-IDs zeigen die Einfügereihenfolge.

| Repeater | Eingebettete ADVERT-Zeit | Koordinaten | Erster OnAir-Empfang und Archivpaket | Empfänge / Signaturen |
| --- | --- | --- | --- | ---: |
| WF-Rodeland `77730034` | 01.03.2026 01:00:05 | 52.167070, 10.554380 | 20.10.2026 07:41:38 · #1040937 | 6 / 1 |
| WF-Rodeland `77730034` | 01.03.2026 01:00:05 | 0, 0 | 27.10.2026 18:31:23 · #1356049 | 3 / 1 |
| WF-Rodeland `77730034` | 01.03.2026 01:00:05 | 52.167090, 10.554400 | 02.11.2026 10:58:51 · #1713208 | 12 / 1 |
| WF-Mitte `bf92b989` | 15.05.2024 12:52:31 | 0, 0 | 15.09.2026 14:48:06 · #63814 | 1 / 1 |
| WF-Mitte `bf92b989` | 15.05.2024 12:52:31 | 52.165830, 10.540430 | 15.09.2026 15:10:51 · #64156 | 1 / 1 |
| WF-Mitte `bf92b989` | 15.05.2024 12:52:31 | 52.165853, 10.538736 | 15.09.2026 19:32:40 · #67589 | 18 / 3 |

Die letzten Empfänge dieser Varianten waren am 17.11. für WF-Rodeland
und am 19.10. für WF-Mitte. Die Koordinaten mit geografisch verwertbaren
Werten derselben ADVERT-Zeit liegen bei WF-Rodeland 2,61 m und bei
WF-Mitte 115,57 m auseinander. Vor dem TRACE lagen für beide neuere
ADVERT-Zeitstempel an den zuletzt projizierten Koordinaten vor
(Archivpakete **2649712** und **2651789**). Die Rohdaten- und die
Schema-16-Positionsabfrage lieferten am TRACE dieselben vier Positionen.

Das Bit `0x10` kennzeichnet im ADVERT zwei vorhandene
Koordinatenfelder. Fehlt das Bit, liefert der Decoder `None`.
Die Nullkoordinaten in der Tabelle sind mit Flags `0x92` ausdrücklich
kodiert. Die lokalen Firmwarestände MeshCore `26079dea`, Gessaman
`2cd32412` und ZephCore `de9471b` lassen die Felder bei
`ADVERT_LOC_NONE` weg. Die Builder für geteilte oder konfigurierte
Koordinaten können zwei Nullen kodieren. Die Repeater-Standardwerte
für nicht konfigurierte Koordinaten sind null. OnAirs Distanzfunktion
verwirft `(0, 0)` bereits als Kartenpunkt, die SQL-Konfliktabfrage
zählt das Paar jedoch als Koordinatenvariante. Für WF-Mitte verbleibt
auch ohne die Nullvariante ein älterer Widerspruch.

#### Vergleich mit identischem Archivstand

Alle historischen Varianten wurden in derselben SQLite-Lesetransaktion
mit dem engen Zeitfenster der sechs Werte aus `trace_sample` für
`measurement_id=2654806` ausgeführt. Für den Einzelvergleich diente
`packets.id=2654832`.

| Kartierung | Gerichtete Werte auf der Karte | Sperre für diese Route |
| --- | ---: | --- |
| Einzelkarte vor Sprint 2 (`1b64c54`) | 4 | 3-Byte-Präfixkollision `777300` zwischen `77730034…` und `777300a2…` |
| Historische Karte vor SQL-Optimierung (`b80d7e5`) | 2 | Archivweite Standortprüfung für `77730034…` und `bf92b989…` |
| Historische Karte nach SQL-Optimierung (`69e54a4`) | 2 | Dieselben beiden Standortkonflikte |
| Historische Karte vor Sprint 3 (`c9f69e0`) und mit Sprint 3 vor der Standortkorrektur | 2 | Dieselben beiden Standortkonflikte |
| Einzelvergleich seit Sprint 2 | 2 | Dieselben beiden Standortkonflikte |

`b80d7e5` führte die archivweite Standortprüfung ein und band sie
auch im Einzelvergleich ein. Die erste Abfrage gruppiert signierte
ADVERTs nach vollständigem Key und eingebettetem Zeitstempel.
Die Optimierung in `69e54a4` ändert den Indexzugriff, das Ergebnis
für den Referenzfall bleibt gleich. Ein isolierter Positionsabruf
ohne Standortbewertung liefert mit der aktuellen 4-Byte-Identitätsauflösung
alle Endpunkte für die drei Strecken. Das erklärt den konkreten
Ausschluss, belegt aber noch keine zeitbezogene Standortfreigabe.
Die 4-Byte-Auflösung unterscheidet die Schlüssel mit Präfix
`777300`. Der 3-Byte-Schutz greift weiterhin bei Funkfeuer
(`dd4c42a1…` und `dd4c42d1…`).

Der Backfill war bis Rohpaket **2637746** abgeschlossen. Alle
Empfänge von `C5355091` liegen darüber und wurden beim laufenden
Schreiben projiziert. Die Standortprüfung liest die ADVERT-Belege
bei der Abfrage. Der Backfill fügt dafür keine ADVERTs hinzu.
`/api/trace-links` liefert `Cache-Control: no-store`.
Der Browser hält die letzte erfolgreiche Antwort im Arbeitsspeicher
und lädt bei geänderter `trace_revision` erneut. Ein Abfragefehler
lässt den letzten Stand sichtbar. Der 60-Sekunden-Cache des
Einzelvergleichs betrifft im Legacy-Modus nur die Positionshistorie.
Die Standortprüfung läuft auch dann pro Detailabfrage.

Im lokalen Docker-Journal ist ein Wechsel des OnAir-Containers am
26.11. um 23:57:56 Uhr belegt, vor diesem TRACE. Die Prüfsummen der
laufenden Archiv-, TRACE- und Linkkartenmodule stimmten bei der
Diagnose mit dem damaligen Arbeitsstand überein. Die Zugriffslogs zeigen am
27.11. um 00:10:21 und 00:10:34 Uhr den Einzelvergleich für
`/api/map-traces/2654833` und um 00:10:50 Uhr eine Abfrage der
historischen Linkstrecken für 24 Stunden mit `sf=all`.
Eine Wiederholung dieser Abfragen mit dem archivierten Bestand
liefert für beide Ansichten nur WF-Ost ↔ WF-Nord-Ost.
Dieselbe 24-Stunden-Abfrage lieferte nachgestellt auch um 00:07:31 Uhr
vor diesem TRACE nur diese Strecke. Die gespeicherten
Benchmarkantworten zeigen das bereits am 26.11. um 22:04 Uhr
im damaligen Tagesfenster.

Die Zugriffslogs enthalten die Anfragen und HTTP-Statuscodes.
Für die zuvor sichtbaren Strecken fehlt ein gespeicherter
Antwortinhalt oder Browserzustand. Ein Wechsel von drei sichtbaren
auf eine sichtbare Strecke innerhalb derselben historischen
Ansicht ließ sich mit identischem Datenstand nicht reproduzieren.

## Abnahme auf dem lokalen Archiv

Am 26.11.2026 umfasste der Benchmark 2.643.737 Paketzeilen in
Schema 17 und 8.126 TRACE-Empfänge. Das Quellarchiv war lesend
eingebunden. Die Schema-18-Projektion lag in einer separaten
temporären SQLite-Datei. Mit der üblichen 100-ms-Wartezeit bei
leerer Live-Warteschlange dauerte die Aufarbeitung 8,68 s. Das
Abarbeiten der Batches benötigte davon 0,47 s. Der längste
Batch inklusive Projektion und Commit dauerte 10,44 ms. Die
zusätzliche SQLite-Datei belegte nach dem Checkpoint 2.056.192
Bytes (1,96 MiB). Sechs TRACE-markierte Empfänge hatten ein
nicht auswertbares Format und blieben mit Rohreferenz erhalten.

SQL-Werte sind Median aus fünf Abfragen der gerichteten Werte
mit Zeitfilter einschließlich SQLite-Auslesen, ohne Aggregation.
„Gesamt“ pro Zeile umfasst zusätzlich Positionsabgleich,
Observer-Historie und Aggregation im Servercode. JSON-Größen
gelten unkomprimiert ohne HTTP-Header.

| Zeitraum | SQL | Gesamt | JSON | TRACE-Messungen | Werte auf Karte | Linkobjekte |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 24 Stunden | 0,18 ms | 39,48 ms | 1.150 B | 71 | 21 | 1 |
| 7 Tage | 0,17 ms | 36,13 ms | 1.150 B | 71 | 21 | 1 |
| 30 Tage | 0,39 ms | 57,32 ms | 20.870 B | 747 | 163 | 28 |
| gesamter Bestand | 1,80 ms | 93,29 ms | 82.505 B | 3.177 | 1.042 | 106 |

Im gesamten Archivfenster hatten 2.645 Messungen keine kartierbare
Strecke. Die vorhandene Profilhistorie erlaubte für die sichtbaren
Archivmessungen keine belastbare SF-Zuordnung. SF7/SF8 und weitere
Profile wurden deshalb mit gezielten Tests geprüft. Eine bedarfsgeladene
Einzelwertseite der ersten Verbindung im Gesamtfenster benötigte
22,39 ms und 15.528 Bytes JSON.

Chromium lief offline mit den realen Aggregaten des Gesamtzeitraums
bei 1280 × 900 px und lokalen Testkacheln. Vom dekodierten JSON bis
zum zweiten Animationsframe vergingen 29,50 ms. Der Klick bis zur
bestätigten Darstellung inklusive Testinstrumentierung dauerte
87,48 ms. CDP maß den Hauptthread und JS-Heap nach Garbage Collection
in 2,5-s-Fenstern ohne neue MQTT-Meldungen. Der Renderer-PSS ist
die Summe der anteilig zugerechneten Speicherseiten der drei
Chromium-Rendererprozesse der Testsitzung aus `/proc`.

| Zustand | CPU des Hauptthreads | JS-Heap | Renderer-PSS | DOM-Knoten |
| --- | ---: | ---: | ---: | ---: |
| inaktiv vor erstem Anzeigen | 0,148 % | 1,39 MiB | 135,37 MiB | 1.804 |
| aktiv | 0,580 % | 3,34 MiB | 160,37 MiB | 2.507 |
| inaktiv nach Anzeigen | 0,035 % | 3,36 MiB | 148,09 MiB | 2.512 |

Der Heap nach einem Tabwechsel enthält die wiederverwendete Karte,
Filter, Layer und Aggregate. Die CPU-Zahlen sind lokale Stichproben
einschließlich des üblichen UI-Hintergrundaufwands. Tile-Netzwerk
und Belastung durch den produktiven MQTT-Strom lagen außerhalb
der Messung.

```bash
PYTHONPATH=. .venv/bin/python tools/benchmark_trace_history.py data/onair.sqlite3 \
  --fixture-dir /tmp/onair-trace-benchmark --sample-id 2604758
.venv/bin/python -m unittest discover -s tests -v
for test in tests/test_*ui.js; do deno run --allow-read=static "$test" || exit; done
.venv/bin/python tests/browser_trace_links.py --benchmark /tmp/onair-trace-benchmark
.venv/bin/python tests/browser_trace_map.py
.venv/bin/python tests/browser_map_visibility.py
.venv/bin/python tests/browser_responsive.py
```

252 Python-Tests und 18 Deno-Skripte bestanden. Chromium prüfte helles
und dunkles Theme, Zoom-Beschriftungen, Canvas und Layer-Wiederverwendung,
Funkprofil- und Zeitfilter, WebSocket-Aktualisierung, Lazy Loading,
Messgruppenvergleich, Kartenkollisionen sowie die responsiven Ansichten.

### Benchmark-Diagnose nach einem abgebrochenen Lauf

Eine ältere Variante der Standortprüfung verglich den Ausdruck
`json_extract(…public_key)` direkt mit einer TEXT-Spalte aus einem
`CROSS JOIN`. SQLite 3.46.1 plante für jeden bewegten Knoten
`SCAN source.packets USING INDEX packets_advert_key_received`.
Der Index umfasste rund 233.000 ADVERT-Zeilen.
Die langsamere Variante wurde auf dem lokalen Archiv mit einem
3-s-Limit reproduziert und abgebrochen. Die wiederholte Aggregation
für vier Zeitfenster verstärkt diesen Aufwand.

Die Standortprüfung ermittelt die relevanten bewegten Schlüssel jetzt
aus der Positionshistorie und übergibt sie getrennt als JSON-Liste.
SQLite plant dafür `SEARCH source.packets USING INDEX
packets_advert_key_received (<expr>=?)`. Backfill und Messwertabfrage
verwenden weiterhin `packets_kind_id` beziehungsweise `trace_sample_time`
als Bereichssuche. Die Prüfung benötigt keinen neuen Archivindex.

Der Kontrolllauf auf 2.645.802 Paketzeilen unter Schema 18 brauchte
10,40 s einschließlich 9,20 s Backfill. Die reine SQL-Abfrage im
Gesamtzeitraum lag bei 1,73 ms im Median. Die vollständige
Aggregation lag bei 88,95 ms. Der Kontrolllauf lieferte erneut
8.126 TRACE-Empfänge, 1.042 kartierbare Werte und 106 Linkobjekte.
Die genaue Abfrage des manuell beendeten Laufs ist mangels eines
Abschnittsprotokolls offen.

Der Benchmark meldet Fortschritt mit Zeitstempeln auf Standardfehler,
einschließlich Archivbestand, Batch-Fortschritt und jedem Messdurchlauf.
Das JSON auf Standardausgabe enthält Laufzeiten je Abschnitt und
die Gesamtzeit. `--timeout 60` setzt das Standardlimit für den
gesamten Lauf. SQLite prüft die Deadline auch während einer laufenden
Abfrage. Beim Timeout endet das Programm mit Code 124. Ctrl+C
und SIGTERM enden mit 130 beziehungsweise 143. Die temporäre
Projektion wird in allen drei Fällen aufgeräumt. JSON-Fixtures
werden erst nach abgeschlossener Messung veröffentlicht.

### Messung der Netzqualitätsanalyse

Die Vergleichsläufe am 26.11.2026 verwendeten das lokale Archiv
im Lesemodus. Zwischen der Messung des Ausgangsstands und der
Sprint-Fassung wuchs das Archiv von 2.652.434 auf 2.653.170 Paketzeilen.
Beide Läufe projizierten 8.128 TRACE-Empfänge, 3.179 TRACE-Messungen
und 1.042 kartierbare Hop-Werte auf 106 Kartenobjekte im Gesamtfenster.
Die neue Statistik enthält 1.065 richtungs- und profilgetrennte
repräsentative Werte für diese Strecken, einschließlich eindeutig
zugeordneter Hops ohne sichere Geometrie. Der Gesamtzeitraum enthält
403 TRACE mit gerichteten Werten und ohne kartierbare Strecke.

| Zeitraum | Aggregation vorher | Aggregation Sprint 3 | JSON vorher | JSON Sprint 3 | Sprint 3 mit Gzip |
| --- | ---: | ---: | ---: | ---: | ---: |
| 24 Stunden | 35,00 ms | 35,91 ms | 1.150 B | 2.353 B | 1.044 B |
| 7 Tage | 34,60 ms | 35,24 ms | 1.150 B | 2.353 B | 1.043 B |
| 30 Tage | 53,96 ms | 54,48 ms | 20.870 B | 36.636 B | 6.696 B |
| Gesamt | 90,05 ms | 91,01 ms | 82.505 B | 148.097 B | 23.766 B |

Die Medianwerte beruhen auf je fünf Aggregationen ohne HTTP-Transfer.
Im Gesamtfenster dauerte die reine SQL-Stichprobenabfrage 1,74 ms,
die Gzip-Kompression 0,71 ms. Eine Einzelwertseite benötigte 21,43 ms
und 15.743 Bytes JSON vor Kompression. Der Backfill dauerte in beiden
Läufen 9,17 s und belegte 2.056.192 Bytes in der temporären Projektion.
Der vollständige neue Lauf endete nach 10,36 s einschließlich
Rohbeispiel und Fixture-Ausgabe. Das 60-s-Gesamtlimit und die
Bereinigung bei Timeout blieben wirksam. Schema und Archivindizes
sind identisch.

Offline-Chromium benötigte bei 1280 × 900 px vom dekodierten
Gesamt-JSON bis zur Darstellung 32,2 ms im Ausgangsstand und
26,6–34,3 ms in zwei Läufen mit der Analyse. Einschließlich Testklick
und Instrumentierung waren es 132,6 und 136,2–137,6 ms.
Moduswechsel dauerten 18,1–33,5 ms bis
zum zweiten Animationsframe und verursachten null zusätzliche
Abfragen. Die Karte verwendete dieselben Canvas-Objekte wieder.
Der Standardmodus erzeugte null permanente Labels. Der aktive
JS-Heap nach Speicherbereinigung lag bei 3,49 MiB vorher und 3,66–3,67 MiB
mit der Analyse. Der Renderer-PSS lag bei 154,6 und 156,1–156,6 MiB.
Im 2,5-s-Messfenster nach Verlassen des TRACE-Tabs beanspruchte
dessen Browserseite einschließlich der übrigen UI rund 0,05–0,06 %
Hauptthread-CPU. Kacheln und MQTT waren für diese Messung simuliert.

Das Archiv lieferte für keine der 106 kartierbaren historischen
Strecken ein vollständiges zugeordnetes Observer-Profil. Die Karte
ließ damit Reserve, Asymmetrie und SF7-Schätzung offen. Die Abdeckung
fiel wegen fehlender Profilzuordnung in die unterste Stufe. Numerische
Klassen, Profilkonflikte und die SF7-Schätzung wurden mit gezielt
erzeugten Testdaten geprüft. Die Sichtprüfung umfasste Desktop,
Hoch- und Querformat sowie beide Themes. Die Zeiten von fünf Sekunden,
30 Sekunden und fünf Minuten bleiben Designziele ohne Messung mit
Testpersonen. Ein Feldvergleich von SF7 und SF8 steht aus.
