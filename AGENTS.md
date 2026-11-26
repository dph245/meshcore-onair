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
