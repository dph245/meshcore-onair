# Observer-Radioprofile und Konfigurationshistorie

OnAir verarbeitet die bestehenden MQTT-Statusmeldungen im Web- und
Terminalbetrieb. Die Weboberfläche zeigt unter Name und Noise Floor pro
Observer die gemeldete Frequenz, Bandbreite, den hervorgehobenen Spreading Factor
und die Coding Rate. Ein Strich steht für einen fehlenden Wert. Wenn ein
bekannter Kernparameter seit 24 Stunden nicht erneut gemeldet wurde, steht
„veraltet“ beim Profil. Bei getrennter Verbindung erscheinen vorhandene Profile
als zuletzt gemeldet. Der Tooltip zeigt die vollständige ID, die letzte
Profilangabe und vorhandene Zusatzparameter. Der Noise-Floor-Plot verwendet wie
bisher ganzzahlige Messwerte. Snapshots enthalten den aktuellen Profilstand.
Der WebSocket sendet die Profilliste im laufenden Betrieb bei Änderungen von
Profilen, Bestätigungszeiten oder Widerspruchsstatus. Im Browser bleiben die
Knoten unveränderter Zeilen erhalten.

## Verifizierte MQTT-Formate

Die folgende Zuordnung stützt sich auf die Serializer und Aufrufer der
eingesehenen Quellstände. Die Testmeldungen bilden diese Quellen nach.

| Feld | Gessaman | openHop Repeater |
| --- | --- | --- |
| `radio` | Zeichenkette `MHz,kHz,SF,CR` aus den Observer-Einstellungen. Format `%.6f,%.1f,%d,%d` | Dieselbe Reihenfolge. Der MQTT-Handler übernimmt eine aus der Repeater-Konfiguration gebildete Zeichenkette. `config.py` rechnet Hz in MHz bzw. kHz um. |
| `firmware_version`, `client_version`, `model` | Firmwareversion, `meshcore/<Version>`, Board-Bezeichnung | App-Version, `openhop_repeater/<Version>`, `openHop-Repeater` |
| `origin_id`, `origin` | Vollständiger Geräte-Public-Key und Anzeigename | Vollständiger Public Key und Anzeigename |
| `timestamp` | UTC mit Offset und Mikrosekunden im geprüften Stand | ISO 8601 mit UTC-Offset |
| `stats.noise_floor` | Optional, dBm | Optional, dBm |

Quellen ([Gessaman MQTTBridge](https://github.com/agessaman/MeshCore/blob/2cd3241288b90f2b5a0a93c187aa7a0759b4e1ea/src/helpers/bridges/MQTTBridge.cpp),
[Gessaman MQTTPayloadBuilder](https://github.com/agessaman/MeshCore/blob/2cd3241288b90f2b5a0a93c187aa7a0759b4e1ea/src/helpers/MQTTPayloadBuilder.cpp),
[openHop MQTT-Handler](https://github.com/openhop-dev/openhop_repeater/blob/13eb8b2ea8b1cdb4a07ed6e282dc99e3aa8a5a8b/repeater/data_acquisition/mqtt_handler.py),
[openHop Konfigurationsadapter](https://github.com/openhop-dev/openhop_repeater/blob/13eb8b2ea8b1cdb4a07ed6e282dc99e3aa8a5a8b/repeater/config.py),
[openHop Statusstatistik](https://github.com/openhop-dev/openhop_repeater/blob/13eb8b2ea8b1cdb4a07ed6e282dc99e3aa8a5a8b/repeater/data_acquisition/storage_collector.py)).

Beispiel für `radio` ist `"869.618000,62.5,8,8"`. OnAir speichert
`frequency_hz=869618000`, `bandwidth_hz=62500`, `spreading_factor=8` und
`coding_rate=8` als Nenner von 4/8. SF5 bis SF12 sind darstellbar. Bei
`client_version=meshcore/…` ist die Familie MeshCore bekannt. Mehrere
Firmwarevarianten können diese Kennung verwenden.

Die beiden geprüften Status-Serializer liefern TX-Leistung, Präambellänge,
Sync Word und Radio-IC nicht mit. Ein Board-Modell sagt allein nichts Eindeutiges
über diese Werte aus. Für Erweiterungen akzeptiert der Parser zusätzlich ein
strukturiertes `radio`-Objekt mit expliziten Feldern `frequency_hz`,
`bandwidth_hz`, `spreading_factor`, `coding_rate`, `tx_power_dbm`,
`preamble_length`, `sync_word` und `radio_ic`. Einheiten sind ganze Hz,
dBm, Symbole und numerisches Sync Word. `4/8` und `0x1424` sind zulässige
Schreibweisen für CR beziehungsweise Sync Word. `firmware` und
`firmware_version` stehen auf der obersten Ebene. Leere, ungültige,
nicht unterstützte und fehlende Felder liefern keine neue Information und
erneuern die Bestätigung eines vorhandenen Werts nicht.

Vollständige hexadezimale IDs werden für die Radioprofile vereinheitlicht.
Bei `meshcore/{IATA}/{PUBLIC_KEY}/status` kann der Schlüssel fehlendes
`origin_id` ersetzen. Stimmen Topic und Payload-ID dort nicht überein,
verwirft OnAir das Radioprofil. Bei anderen bestehenden Status-Topics, etwa
`meshcore/repeater/{name}/status` von openHop, muss die Payload eine ID
enthalten. Anzeigenamen dienen der Darstellung. Ein gegebenenfalls vom
Observer gemeldetes Profil belegt die gemeldete Einstellung. openHop sendet im
geprüften Serializer das aus der Konfiguration übernommene Profil, bei einem
Gerät mit mehreren Radios ordnet diese Meldung das Profil keinem
konkreten Empfang zu.

## Schema 17 und zeitliche Zuordnung

Die Migration legt zwei Tabellen mit zusammengesetztem Primärschlüssel auf
`(origin_id, observed_at)` sowie einen partiellen Index für offene Widersprüche
an. Der bestehende Archivschreiber übernimmt die Meldung in seiner
SQLite-Transaktion. Nach dem Commit steht der neue Stand im Speicher für den
WebSocket bereit. Beim Neustart lädt OnAir den jüngsten Eintrag pro Observer.

- `observer_radio_history` enthält die erste bekannte Kombination und je
  Änderung oder neu bekanntem Feld eine weitere Zeile. Identische Werte
  aktualisieren nur die Bestätigungszeit und die Zeit der tatsächlich
  enthaltenen Felder. Dieselbe Quellzeit mit identischen Werten ist ein Duplikat.
- `observed_at` ist der Quellenzeitpunkt der ersten Meldung mit der geänderten
  Kombination oder ersatzweise der Empfangszeitpunkt. `detected_at` ist der
  lokale MQTT-Empfang. `source_timestamp` und `retained` halten die Herkunft
  beim Anlegen der Zeile fest. Eine ISO-8601-Zeit ohne Offset gilt wie im
  bisherigen Noise-Floor-Pfad als UTC. Mehr als 60 Sekunden nach dem lokalen
  Empfang liegende Quellzeiten verwirft OnAir. Zeiten vor
  2000 gelten als unbrauchbar. Eine Live-Meldung ohne brauchbare Quellzeit kann
  mit der lokalen Empfangszeit als unsichere Beobachtung eingehen.
- Ein retained Status mit brauchbarer Quellzeit kann die Historie beginnen
  oder einen älteren Stand aktualisieren. Der Empfang beim
  Reconnect macht die Meldung nicht aktueller. Ältere Meldungen und retained
  Wiederholungen mit derselben Zeit verschieben den aktuellen Stand nicht.
  Offline-Meldungen bestätigen das Radioprofil nicht.
- `transition_after` enthält bei einer Änderung den frühesten letzten
  Bestätigungszeitpunkt der veränderten, zuvor bekannten Felder. Der Wechsel
  wurde spätestens bei der neuen Beobachtung sichtbar. Der genaue
  Gültigkeitsbeginn bleibt offen.
- `observer_radio_conflicts` kennzeichnet widersprüchliche Live-Angaben
  desselben Observer-Zeitpunkts. Das Intervall reicht bis zur nächsten
  Bestätigung aller betroffenen Felder. Eine Teilmeldung zu anderen Feldern
  schließt es nicht.

`Archive.observer_radio_at(origin_id, received_at)` erwartet die vollständige
Observer-ID des RX-Datensatzes und seinen UTC-Unix-Zeitstempel, zum Beispiel
aus `packets.received`. Abfragen, die viele Empfänge auswerten, können
`radio_profile_at(db, origin_id, received_at)` in einer gemeinsamen
Lesetransaktion aufrufen.

| Ergebnis | Bedeutung |
| --- | --- |
| `confirmed` | Die Quellzeit entspricht einer gespeicherten vollständigen Meldung der vier Kernparameter. Pro Profilzeile bleiben der erste und letzte solche Zeitpunkt erhalten. |
| `last_known` | Das zuletzt beobachtete Profil ist verfügbar, unter Umständen mit einzelnen fehlenden Feldern. Seine Gültigkeit zum angefragten Zeitpunkt ist unbelegt. |
| `unknown` | Vor erster Beobachtung, ohne bekannte Kernparameter, während eines erkannten Übergangs oder bei widersprüchlichen Meldungen. |

Ein bestätigt gemeldetes Observer-Profil belegt vier gemeinsam gemeldete
Kernparameter zu diesem Zeitpunkt. Zusatzfelder können älter sein.
`known_valid_from` bleibt `None`, da die geprüften Formate keinen wirksamen
Umschaltzeitpunkt senden. Auch zwischen gleichen Statusberichten bleibt eine
unbemerkte Änderung prinzipiell möglich. Das Ergebnis gehört ausschließlich
zum empfangenden Observer. Für die Sender entlang eines TRACE-Pfads wären
eigene Beobachtungen nötig.

## Archivprüfung

Die lokale Schema-16-Datenbank enthält in `noise_samples` lediglich Noise
Floor, Observer-ID, Name und Zeitstempel. Die 37 archivierten
MQTT-Originalpayloads in `rf_neighbor_messages` gehören zum Topic
`/neighbors`. Das Paketarchiv enthält bereits dekodierte Paket-Metadaten.
Eine Stichprobe der jüngsten 512 Zeilen bestätigt die Felder des aktuellen
Paketmodells. Es war kein lokaler Rohmitschnitt von `/status` verfügbar.
Die Migration legt deshalb eine leere Profilhistorie an. Eine zeitlich
belastbare Rückrechnung aus den vorliegenden Daten ist nicht möglich.

Eine passive Stichprobe auf `meshcore/+/+/status` am konfigurierten Broker
lieferte fünf retained Meldungen, alle älter als 24 Stunden. Drei trugen
die Radio-Zeichenkette. Zwei davon waren Offline-Meldungen. Der verbleibende
Profilbericht liefert einen einzelnen Beobachtungszeitpunkt und würde
als veraltet erscheinen. Die Stichprobe bestätigte das Drahtformat. Die
Zuordnung zu Gessaman und openHop beruht auf den jeweiligen Firmwarequellen.

## Abnahme und Performance

Der Benchmark öffnet das lokale Archiv im Lesemodus. Er zählt die Pakete
einmal über den bestehenden Index und entnimmt dem Tabellenende eine begrenzte
Stichprobe mit Empfangszeit und Observer-ID. Das
Schreiben beschränkt sich auf temporäre SQLite-Tabellen mit Produktionsschema
und synthetischen Statusmeldungen. Die Messung erfasst wiederholte Abfragen auf
einer vorhandenen Verbindung einschließlich Python-Normalisierung und
JSON-Decodierung.

```bash
PYTHONPATH=. .venv/bin/python tools/benchmark_observer_radio.py data/onair.sqlite3
.venv/bin/python -m unittest discover -s tests -v
deno run --allow-read=static tests/test_noise_ui.js
.venv/bin/python tests/browser_live_render.py
```

Am 26.11.2026 hatte das lokale Archiv 2.636.470 Pakete und 8,33 GiB. 20.000
simulierte Statusmeldungen für fünf Observer ergaben 10.000 Profilzeilen.
11.000 Profilabfragen dauerten im Median 6,11 µs, das 95. Perzentil lag bei
7,64 µs. SQLite 3.46.1 verwendete für die vorangehende und die folgende
Beobachtung sowie für die Konfliktabfrage jeweils `SEARCH … USING PRIMARY KEY`.
Die eigentliche Profilabfrage liest keine Pakete. Die Messwerte gelten für den
lokalen Test mit synthetischer Profilhistorie.

Die vollständige Regression umfasst 240 Python-Tests, 17 Deno-Skripte
und einen Chromium-Lauf für die Live-Oberfläche. Die neuen Prüfungen
decken insbesondere Mischprofile, den Wechsel SF8 → SF7 → SF8,
Teilstatus, verspätete und retained Meldungen, Neustarts, Migration und
inkrementelle Anzeige ab. Chromium prüft auch, dass ein Paket-Delta
ohne Statusänderung den Observer-Header im DOM unverändert lässt.
