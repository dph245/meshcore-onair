# OnAir

- OnAir ist ein passiver MQTT-Subscriber. Änderungen an der Analyse bleiben
  im bestehenden Datenpfad für Observer-Feeds.
- `onair_mqtt.py` nimmt Paket- und Statusmeldungen an. `onair_archive.py`
  migriert und schreibt das SQLite-Archiv. `onair_web.py` versorgt die
  statische Oberfläche über HTTP und sequenzierte WebSocket-Nachrichten.
- Neue Felder im WebSocket-Status müssen beim Snapshot vollständig vorliegen.
  Unveränderte Radioprofile fehlen in laufenden Updates. Der Browser behält
  dafür den Stand des letzten Snapshots bzw. Updates.
- Für Observer-Profile sind vollständige IDs, explizite Einheiten und die
  Unterscheidung zwischen Quellzeit und OnAir-Empfang maßgeblich.
  Der Stand `confirmed` belegt eine gemeldete Einstellung zu einem
  beobachteten Zeitpunkt. Für TRACE-Auswertungen braucht jeder Sender seine
  eigene Datengrundlage. Siehe [Observer-Radioprofile](docs/observer-radio.md).
- Für Regressionstests eine temporäre SQLite-Datei verwenden. Die große
  lokale Datenbank kann für Abfragemessungen im Lesemodus geöffnet werden.
  Der Radio-Benchmark schreibt dort nur temporäre Tabellen.
- Tests lassen sich mit `.venv/bin/python -m unittest discover -s tests -v`
  sowie den Deno- und Chromium-Skripten unter `tests/` ausführen.
  Der aktuelle Arbeitsstand steht in [PROJECT_STATUS.md](PROJECT_STATUS.md).
- Schema 18 projektiert TRACE-Empfänge inkrementell in
  `onair_trace_history.py`. Der Archivschreiber nutzt `packets_kind_id`
  für den wiederaufnehmbaren Backfill; maßgeblich sind Rohpaket-ID, Protokollfolge
  und SNR am empfangenden Hop. Die Übersicht in `static/trace-links.js` verwendet
  dieselbe Leaflet-Karte wie der Einzelvergleich. Modell, Korrelation und
  Offline-Benchmarks stehen in [Historische TRACE-Linkstrecken](docs/trace-history.md).
- Die Linkbewertung verwendet `RULES` in `onair_trace_quality.py` und
  rechnet getrennt nach Richtung und exaktem Observer-Profil. Je Richtung
  und Profil zählt jeder korrelierte TRACE höchstens einmal. Der Browser
  schaltet Modi, Kategorien und Sortierung auf geladenen Aggregaten um.
  Einzelwerte und Empfangsbelege laden bei Bedarf. Referenzwerte, Stichprobe
  und Grenzen der SF7-Schätzung sind in der
  [Netzqualitätsanalyse](docs/trace-history.md#netzqualitätsanalyse) beschrieben.
