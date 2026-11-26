# Projektstand

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
