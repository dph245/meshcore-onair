# Projektstand

## Historische TRACE-Karte mit gemessener SNR

Stand 27.11.2026. Die Linkübersicht startet mit dem gesamten Bestand,
allen SF und dem Median. Die SNR-Farbskala verwendet je Strecke den
kleineren verfügbaren Richtungswert. Im Tooltip stehen beide
Richtungswerte. Klick oder Touch öffnet den Verlauf für den
gewählten Zeitraum. Die Kartenlabels sind standardmäßig aus.
Die Karte lädt kompakte SNR-Aggregate. Die ausführliche API-Antwort
enthält weiterhin die frühere Netzqualitätsbewertung.

Der Vergleich im Lesemodus ergab für beide API-Varianten dieselben
124 Strecken mit identischen Endpunkten, Positionen und Präfixbreiten.
Die aggregierte Antwort lag bei 25,81 ms im Median und 14.834 Bytes
mit Gzip, gegenüber 28,86 ms und 28.630 Bytes für die ausführliche
Antwort. Chromium benötigte 28,4 ms von der dekodierten Antwort bis
zur Darstellung. Die vier SNR-Statistiken wechselten ohne zusätzliche
Archivabfragen.

[Historische TRACE-Linkstrecken](docs/trace-history.md)

## Initiale TRACE-Kartenzeichnung

Stand 27.11.2026. Beim erneuten Öffnen konnte Leaflet 1.9.4
den abgebrochenen Canvas-Zeichenframe eines entfernten Renderers
weiter als ausstehend behandeln. Die Ansicht verwendet beim
Wiederanhängen einen frischen Renderer für die vorhandenen
Pfad- und Markerobjekte. Die erste Bounds-Berechnung wartet
auf einen sichtbaren Container mit nutzbarer Größe. Ein
Chromium-Pixeltest prüft beide Linien ohne Karteninteraktion,
auch nach Tabwechseln und Layoutänderungen.
[Initiale Kartenzeichnung](docs/trace-history.md#initiale-kartenzeichnung)

## Zeitbezogene TRACE-Standortvalidierung

Stand 27.11.2026. Die historischen Linkstrecken und der Einzelvergleich
verwenden dieselben Standortbelege zur Zeit des jeweils empfangenden
Hops. Die Präfixprüfung bleibt davon unabhängig. Geringe Abweichungen
bis standardmäßig 25 m zählen als derselbe Standort. Neue Phasen
brauchen wiederholte eindeutige Belege. Gesperrte Hops bleiben mit SNR
und konkretem Ausschlussgrund in den Details zugänglich.

- Der echte TRACE `C5355091` ergibt vier eindeutige Repeater und drei
  bidirektionale Strecken mit den sechs archivierten Richtungswerten.
  Der Funkfeuer-Präfixschutz und die Sperre weiter widersprüchlich
  verwendeter vollständiger Keys wurden geprüft.
- Die Positionsabfrage verwendet indexierte Abrufe für beteiligte
  Keys und neue ADVERTs. Im realen Archiv lag die wiederholte
  Gesamtaggregation bei rund 28 ms. Der erste Abruf des gesamten
  Bestands mit leerem Positionscache dauerte rund 251 ms.
- 268 Python-Tests, 19 Deno-Skripte und die beiden Chromium-TRACE-
  Kartenprüfungen bestanden. Der Gzip-Test verwendet echte
  HTTP-Anfragen auf Loopback. Der frühere Hänger beruht auf der
  Socket-Sperre der Sandbox.

Regeln, Referenzdaten und Messwerte stehen in der
[zeitbezogenen Standortvalidierung](docs/trace-history.md#zeitbezogene-standortvalidierung).

## Frühere TRACE-Netzqualitätsansicht, Sprint 3

Stand 26.11.2026. Die damalige historische TRACE-Karte bot Linkqualität,
Asymmetrie, Messabdeckung und eine theoretische SF7-Reserveprognose.
Die kompakte Legende filtert Karte und Auswahlliste. Das vorhandene
Detailpanel führt vom Befund über getrennte Richtungs- und
Profilstatistiken zu Perzentilen, Diagrammen und Empfangsbelegen.

- Die Bewertung zählt korrelierte TRACE je Richtung und Profil und
  verwendet bei ausreichender Stichprobe P10. Asymmetrie setzt
  zeitlich vergleichbare Richtungswerte desselben Profils voraus.
  In der Messabdeckung zählen zusätzlich Zeitspanne, Aktualität und
  Güte der Profilzuordnung.
- Die Modi verwenden die geladenen Aggregate und Kartenobjekte.
  Moduswechsel lösten null Archivabfragen aus. Einzelwerte und
  Empfangsbelege laden auf Anforderung. Schema 18 bleibt maßgeblich.
- Der lokale Gesamtlauf lieferte 106 kartierbare Strecken in
  91,01 ms Aggregationszeit bei 9,17 s Backfill. Chromium stellte
  die dekodierten Aggregate nach 26,6–34,3 ms dar. Die Gesamtantwort
  belegte beim Versand mit Gzip 23.766 Bytes.
- Für die archivierten Strecken fehlten vollständige zeitlich
  zugeordnete Observer-Profile. Die numerischen Ratings wurden mit
  Testdaten geprüft. Die tatsächliche SF7/SF8-Vergleichsmessung
  bleibt offen. Arbeitsstand lokal im Worktree.
- 261 Python-Tests, 18 Deno-Skripte und vier Chromium-Prüfungen
  bestanden. Die visuelle Prüfung umfasste Desktop und Touch im
  Hoch- und Querformat.
- Schwellen, Datenqualitätsregeln, Abfrageverhalten und Messprotokoll
  stehen in der [Netzqualitätsanalyse](docs/trace-history.md#netzqualitätsanalyse).

## Historische TRACE-Linkstrecken, Sprint 2

Stand 26.11.2026. Schema 18 historisiert die TRACE-Beobachtungen aus
dem vorhandenen Observer-Feed. Der Archivschreiber erfasst neue
Empfänge und arbeitet Altzeilen in begrenzten, wiederaufnehmbaren
Batches auf. Die vorhandene TRACE-Karte zeigt aggregierte gerichtete
Strecken mit Zeitraum-, Profil- und SNR-Filter. Rohbelege und
Einzelwerte werden bei Bedarf geladen.

- Die 1-, 2- und 4-Byte-Präfixe bleiben vollständig erhalten. Die
  Kartenprojektion berücksichtigt mehrdeutige Identitäten und
  widersprüchliche historische Positionen. Ein echter 4-Byte-TRACE
  wurde aus den Rohbytes bis zu allen sechs gerichteten Werten geprüft.
- Das Profil stammt aus der Schema-17-Historie der beteiligten Observer.
  In den sichtbaren historischen Archivdaten blieb der SF unbekannt.
  SF7, SF8 und weitere SF wurden in automatisierten Tests geprüft.
- Auf 2,64 Mio. Paketzeilen ergaben 8.126 TRACE-Empfänge 106 sichtbare
  Linkobjekte im Gesamtfenster. Der Backfill dauerte 8,68 s bei
  nachgebildeter Leerlauf-Taktung und benötigte zusätzlich 1,96 MiB.
- 252 Python-Tests, 18 Deno-Skripte und vier Chromium-Prüfungen liefen
  erfolgreich. Arbeitsstand lokal im Worktree. Die Bewertung einer
  SF7/SF8-Messkampagne bleibt ein eigener Sprint.
- Protokoll, Datenmodell, Einschränkungen, Test- und Messwerte stehen
  in [Historische TRACE-Linkstrecken](docs/trace-history.md).
- Die Benchmark-Nachprüfung sichert den ADVERT-Indexzugriff der
  Standortprüfung ab. Der Benchmark meldet Abschnittszeiten und
  hat ein konfigurierbares Zeitlimit von 60 s. Der Kontrolllauf
  auf dem lokalen Schema-18-Archiv dauerte 10,40 s. Die vollständige
  Python-Suite bestand mit 255 Tests.

## Observer-Radioparameter, Sprint 1

Stand 26.11.2026. Web- und Terminalbetrieb verarbeiten Funkprofile über
den bestehenden MQTT-Statusfeed. Schema 17 protokolliert je Observer die
erste Meldung, neue Felder und geänderte Werte. Die Kopfzeile zeigt das
gemeldete Funkprofil neben dem Noise Floor. Die interne Abfrage
`Archive.observer_radio_at` steht für die spätere TRACE-Auswertung bereit.

- Gessaman und openHop senden Frequenz, Bandbreite, SF und CR als gemeinsame
  Zeichenkette. Firmwarefamilie und Version werden aus vorhandenen Metadaten
  übernommen. Für TX-Leistung, Präambellänge, Sync Word und Radio-IC fehlen
  Angaben in den geprüften Statusformaten.
- Im lokalen Archiv fehlt für ältere Zeiträume ein Rohmitschnitt der
  Statusmeldungen. Eine passive Broker-Stichprobe ergab einen auswertbaren
  retained Profilbericht, der älter als 24 Stunden war. Die Historie
  beginnt je Observer mit dem ersten auswertbaren Statusbericht.
- Der lokale Benchmark lief bei 2,64 Mio. Paketzeilen im Lesemodus.
  Die indexierten Profilabfragen lagen bei 6,11 µs im Median. Die
  Profilhistorie im Benchmark war synthetisch.
- 240 Python-Tests, 17 Deno-Tests und die Chromium-Prüfung der Live-Ansicht
  waren erfolgreich.
- Feldzuordnung, Zeitsemantik, Migrationsdetails und Tests stehen in
  [Observer-Radioprofile](docs/observer-radio.md).
