# Projektstand

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
