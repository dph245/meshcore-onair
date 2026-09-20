# MeshCore OnAir

Lokaler, kompakter MQTT-Netzmonitor für den MeshCore Observer.

## Start

Python 3.10 oder neuer, im Projektverzeichnis:

```bash
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn onair_web:app --host 127.0.0.1 --port 8000
```

Im Browser **http://127.0.0.1:8000** öffnen. Der Webserver startet den MQTT-Monitor
mit der bisherigen Terminal-Ausgabe. Ctrl+C beendet beide sauber. Einen einzelnen
Uvicorn-Worker verwenden, damit alle Browser denselben Paketspeicher sehen.

Der bisherige reine Terminal-Modus bleibt verfügbar:

```bash
.venv/bin/python onair_mqtt.py
```

Broker und Topic stehen weiterhin in `onair_mqtt.py`: `192.168.88.40:1883`,
`meshcore/#`. Der Monitor subscribiert ausschließlich; er publiziert nichts und
ändert weder Observer noch BSMesh. Jede Instanz hat eine eigene MQTT-Client-ID.
Der Webmodus versucht bei Ausfällen automatisch die Verbindung wiederherzustellen.
Die Kopfzeile unterscheidet MQTT-Ausfall und WebSocket-Ausfall.

## Liveansicht

Der Schalter **Lightmode / Darkmode** in der Kopfzeile wechselt die Darstellung.
Die Auswahl wird im Browser gespeichert; ohne gespeicherte Auswahl gilt die
Systemeinstellung.

Die Tabs **Live**, **Channels**, **Archiv**, **Nodes** und **Noise Floor** zeigen jeweils einen
Bereich; beim Öffnen ist **Live** ausgewählt. Suchfelder und Ergebnisse bleiben
beim Wechsel erhalten, der Empfang läuft weiter. Die Tabs sind auch per
Pfeiltasten sowie Pos1/Ende bedienbar.

**Channels** bietet die beim Serverstart aus `channels.json` geladenen Kanäle
einschließlich des Standardkanals **Public** zur Auswahl. Beim Kanalwechsel werden
die neuesten 50 gespeicherten Textempfänge angezeigt; ältere lassen sich nachladen.
**Aktualisieren** lädt die neuesten Empfänge nach dem Datenbank-Commit. Empfänge mit
demselben Observer-Hash werden zu einer Nachricht mit aufklappbaren Empfangsdetails
zusammengefasst, auch über nachgeladene Seiten hinweg. Ohne Hash bleiben Empfänge
einzeln. Die Zähler beziehen sich auf die bisher geladenen Empfänge.
Die Auswahl-API `/api/channels` liefert nur Namen,
keine Schlüssel. Nach Änderungen an `channels.json` den Server neu starten und die
Seite neu laden.

Im Tab **Live** filtert **Repeater filtern** sofort nach Hash oder Namen, auch nach
Teilen davon und unabhängig von Groß-/Kleinschreibung. Gesucht wird im letzten Hop
von Flood-Paketen sowie im Public Key und Namen gültiger direkter Repeater-ADVERTs.
Namen stammen aus der vorhandenen Namensauflösung zum Empfangszeitpunkt;
Zielrouten (DIRECT/TC_DIRECT) zählen nicht als Senderpfad.
Bei gruppierten Paketen erscheinen nur passende gespeicherte Empfänge; Hauptzeile,
RSSI und Reihenfolge der Paketgruppen beziehen sich auf den neuesten Treffer. Der Gesamtzähler
der Empfangsgruppe bleibt erhalten, die Zahl passender Empfänge wird zusätzlich angezeigt.
**Zurücksetzen** zeigt wieder alle Pakete. Der Filter bleibt beim Tabwechsel und
WebSocket-Reconnect erhalten und funktioniert auch in der pausierten Ansicht.
Empfang und Archivierung laufen unabhängig vom Filter weiter.

Zeit | Typ | Route | Scope | Inhalt | Last Hop | RSSI | SNR | Hops | Hash / Empfänge

Bei mehreren Empfängen zeigt **Hash / Empfänge** für jeden gespeicherten Empfang
Last Hop und Observer. Die zugehörigen Messwerte stehen auf gleicher Höhe in den
Spalten **RSSI** und **SNR**. Die oberste Zeile zeigt die Werte des neuesten Empfangs.
Die Empfangsliste und die aufgeklappten Details sind nach SNR absteigend sortiert.
Bei gleichem SNR steht der neueste Empfang zuerst; fehlende Messwerte stehen am Ende.

**SNR** zeigt in der Liveansicht neben dem dB-Wert eine dreistufige Balkenanzeige,
auch in der Empfangsliste und den aufgeklappten Empfangsdetails: unter −2 dB ein roter Balken,
von −2 bis einschließlich 0 dB zwei orange Balken, über 0 dB drei grüne Balken.
Ohne Messwert erscheinen keine Balken. Die Grenzwerte stehen zentral als
`snrThresholds` in `static/app.js`; eine Einstellungsoberfläche gibt es dafür noch nicht.

**Scope** ist in Live, Archiv, Channels und der Terminal-Ausgabe sichtbar.
Pakete ohne Transport-Codes erscheinen als **Kein Scope**; bei `TC_FLOOD` und
`TC_DIRECT` wird der Regionsname durch Abgleich des Transport-Codes erkannt.
Die bekannten öffentlichen Scopes sind in `onair_scopes.py` hinterlegt:
`de`, `de-ni`, `de-ni-wf`, `bsmesh`, `de-mitte`, `de-nord` und `de-harz`.
Die Schlüsselableitung verwendet das implizite `#` vor dem Namen gemäß MeshCore.
Nach Änderungen den Server neu starten. Nicht erkannte Regionen erscheinen als
**Unbekannt (0x…)** mit dem ersten Transport-Code als 16-Bit-Hexwert (Little Endian).
Mehrere passende Namen werden als **Mehrdeutig** angezeigt. Der Regionsname wird
nicht im Paket übertragen; der berechnete Code ist keine stabile Regions-ID.
Grundlage sind die
[MeshCore-Scope-Berechnung](https://github.com/meshcore-dev/MeshCore/blob/main/src/helpers/TransportKeyStore.cpp)
und das
[MeshCore-Paketformat](https://github.com/meshcore-dev/MeshCore/blob/main/docs/packet_format.md).
In Live zeigt die Hauptzeile den neuesten passenden Empfang, die Details zeigen
den Scope jedes einzelnen Empfangs. Channels zeigt alle unterschiedlichen
Scope-Anzeigen der geladenen Empfänge einer Nachricht. Die Anzeige funktioniert
auch für bestehende Archiveinträge ohne Datenbankmigration.

Bei `GRP_TXT` zeigt Inhalt den Kanal und Nachrichtentext samt Absendernamen.
Bei `ADVERT` zeigt Inhalt den Node-Namen, Typ (Chat, Repeater, Room-Server oder
Sensor) und die Position, sofern enthalten. Die Empfangsdetails enthalten außerdem
Public Key, Advert-Zeitstempel, Flags, optionale Feature-Felder und die Signatur.
Die Ed25519-Signatur wird geprüft und ihr Ergebnis angezeigt. Ungültige oder nicht unterstützte
ADVERT-Payloads werden entsprechend markiert; die Rohdaten bleiben verfügbar.
Lange Texte und Zeilenumbrüche vergrößern die Zeile automatisch.
Der öffentliche Standardkanal wird automatisch entschlüsselt. Eigene Kanäle
in `channels.json` neben den Python-Dateien eintragen, beispielsweise:

```json
{
  "#dein-kanal": null,
  "Mein privater Kanal": "HIER_HEX_ODER_BASE64_SCHLUESSEL_EINTRAGEN"
}
```

`channels.example.json` dient als Vorlage. Nicht benötigte Einträge entfernen
und den Platzhalter durch den tatsächlichen Kanalschlüssel ersetzen (16 oder
32 Byte, als Hex oder Base64). Bei Hashtag-Kanälen reicht der exakte Name mit
`#` und der Wert `null`; daraus wird der Schlüssel abgeleitet.
Nach Änderungen den Server neu starten. `channels.json` wird von Git ignoriert;
Schlüssel werden nicht an den Browser übertragen. Ohne passenden Schlüssel
erscheint „Nicht entschlüsselbar“; Raw- und Payload-Hex bleiben in den Details.
Die Implementierung folgt dem [MeshCore-Payloadformat](https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md)
und der [MeshCore-Verschlüsselung](https://github.com/meshcore-dev/MeshCore/blob/main/src/Utils.cpp).

Auf die Zeit klicken, um die einzelnen Empfänge mit vollständigem Pfad,
Transport-Code, Raw-Hex, Payload-Hex, Header und weiteren Decoder-Feldern zu sehen.
Die Hauptzeile zeigt den neuesten Empfang der Gruppe. Gleiche Observer-Hashes
(ohne Beachtung der Groß-/Kleinschreibung) werden zusammengefasst, auch wenn sich
Route oder Messwerte ändern. Ohne Hash wird jeder Empfang separat angezeigt.
Unter `… Empfänge` steht pro gespeichertem Empfang der letzte Hop untereinander,
mit Namensauflösung über `ALIASES` in `onair_mqtt.py`. Wiederholte Repeater bleiben
als eigene Zeilen erhalten; ein Empfang ohne Hops erscheint als `direct`.
Angezeigt werden die bis zu 50 gespeicherten Empfänge. Der Gruppenzähler zählt
Empfangsbeobachtungen über alle Observer, keine nachgewiesenen Weiterleitungen:
Dasselbe Paket an Ost und West ergibt zwei Empfänge, auch bei nur einer Aussendung.
Die Webansicht nimmt nur Nachrichten mit `direction: rx` auf.

Maximal 500 zuletzt aktive Gruppen und 50 letzte Empfänge je Gruppe bleiben im RAM.
Der Gruppenzähler zählt auch bereits entfernte Empfangsdetails; nach Verdrängung
der gesamten Gruppe beginnt er bei erneutem Empfang neu. Der Terminal-Zähler
hält separat maximal 5000 Hashes. Die Liveansicht beginnt beim Neustart leer; das Archiv bleibt erhalten.
Die Übergabe von MQTT ist auf 2048 wartende Pakete begrenzt; verworfene Web-Empfänge
werden in der Werkzeugleiste gezählt. Langsame Browser erhalten einen aktuellen
Snapshot. Nach einer WebSocket-Neuverbindung wird die Ansicht ebenfalls synchronisiert.
„Ansicht pausieren“ friert nur die Darstellung ein; der Empfang läuft weiter.

Ein-Byte-Hop-Hashes werden niemals auf Aliase abgebildet. Bekannte Präfixe ab zwei
Byte bleiben wie im vorhandenen Parser aufgelöst. Die Tabellenzeit kommt vom
Observer; die Details enthalten zusätzlich die lokale Empfangszeit mit Zeitzone.
Die Radioangaben im Kopf sind die konfigurierte Vorgabe, keine Live-Telemetrie.
Andere Payload-Typen werden weiterhin als Hex in den Details angezeigt.

## SQLite-Archiv und gelernte Namen

Das Widget **Noise Floor · Raw / Step** zeigt je Observer die letzten 500 gültigen
`stats.noise_floor`-Messungen als separaten Step-Plot mit sichtbaren Messpunkten und
eigener Skala. Die Trennung erfolgt anhand der vollständigen `origin_id`, nicht
anhand des Anzeigenamens `origin`. Namen und die ersten drei Bytes der Kennung
stehen am Graphen und neben dem letzten Noise-Floor-Wert in der Kopfzeile; der
Tooltip enthält die vollständige ID und die letzte Empfangszeit. Jede
Statusmeldung bleibt als eigener Messpunkt erhalten, auch bei identischen Werten.
Es gibt keine Glättung, Mittelung oder lineare Interpolation: Die Linie hält den
Wert bis zur nächsten Meldung desselben Observers und springt dort vertikal auf den neuen Wert.
Hover, Berührung oder Tastaturfokus auf einem Punkt zeigen den exakten
ISO-Zeitstempel mit Zeitzone und den ganzzahligen dBm-Wert. Die Zeit ist die lokale
MQTT-Empfangszeit, kein vom Heltec gelieferter Messzeitstempel.

Web- und Terminal-Modus speichern diese Werte dauerhaft in der SQLite-Tabelle
`noise_samples` einschließlich `origin_id`, `origin` und `status_at`; Schema 8 ergänzt die
vorhandene Datenbank automatisch. Historische Werte ohne Observer-ID bleiben in
einer separaten Reihe „Unzugeordnet“. Nach einem Neustart oder Browser-Reconnect
lädt das Widget wieder die letzten 500 Werte **pro Observer**.
Ältere Messungen bleiben in SQLite erhalten. Fehlende, nicht endliche und nicht
ganzzahlige Werte werden ausgelassen, ohne sie zu runden oder durch null zu ersetzen.
Die Ansichtspause gilt auch für den Graphen; der Empfang und die Speicherung laufen
weiter. Observer werden nach 24 Stunden ohne neue Noise-Floor-Statusmeldung in
Graph und Kopfzeile ausgeblendet (auch ohne weitere MQTT-Meldungen). Dafür zählt
`timestamp` aus der Statusmeldung (`status_at` im Archiv), sofern vorhanden;
offsetlose Zeitstempel werden als UTC interpretiert. Nur bei Live-Meldungen ohne
gültigen Quellzeitstempel dient die lokale Empfangszeit als Ersatz. Alte
MQTT-Retained-Meldungen werden beim Reconnect nicht durch die neue Zustellzeit
wieder aktiv. Retained-Meldungen ohne gültigen Quellzeitstempel werden nicht als
Noise-Floor-Messung übernommen. Historische Einträge behalten ihre ursprünglichen
lokalen Empfangszeiten; sobald eine Statusmeldung mit Quellzeit eintrifft, ist diese
für die Altersprüfung des Observers maßgeblich. Eine neue
Messung blendet sie einschließlich ihrer erhaltenen Historie wieder ein. Die
Archivdaten werden nicht gelöscht. Die Historie bleibt bei kürzeren Verbindungsabbrüchen sichtbar; die Kopfzeile zeigt
den Verbindungsstatus. Es werden keine zusätzlichen Messpunkte erzeugt.

Web- und Terminal-Modus speichern jeden erfolgreich geparsten RX-Empfang inklusive
Wiederholungen, Raw-Paket, decodierter Inhalte, Pfad und Messwerten. Fehlerhafte
Raw-Pakete, die der bisherige Decoder verwirft, werden weiterhin nur protokolliert.
Die Datei `onair.sqlite3` wird beim Start neben den Python-Dateien angelegt.
Ein anderer Speicherort lässt sich für eine spätere SSD-Migration einstellen:

```bash
ONAIR_DB_PATH=/pfad/auf/ssd/onair.sqlite3 .venv/bin/python -m uvicorn onair_web:app --host 127.0.0.1 --port 8000
```

Ein eigener Schreibthread bündelt maximal 100 Empfänge oder fünf Sekunden in einer
Transaktion. SQLite verwendet WAL und die voreingestellte FULL-Synchronisierung.
Beim sauberen Beenden wird der Rest geschrieben. Bei Stromausfall können noch
gepufferte Empfänge fehlen. Bei Schreibfehlern wird erneut versucht; maximal
10.000 weitere Empfänge warten im RAM. Überläufe und Schreibfehler werden im
Terminal und in der Live-Werkzeugleiste gemeldet. Ein fehlgeschlagenes abschließendes
Speichern wird als Fehler gemeldet. Liveansicht und Archiv haben getrennte Puffer.

Im Bereich **Archiv** nach Text, Hop, gespeichertem Node-Namen oder Hash suchen;
Typ, Kanal und lokalen Zeitraum optional einschränken. Ergebnisse erscheinen als
einzelne Empfänge in Seiten zu 50 Einträgen, Details durch Aufklappen. Neue Empfänge
sind nach dem nächsten Commit suchbar. Namen und Texte werden in ihrem Zustand zum
Empfang gespeichert; spätere Namensänderungen verändern alte Einträge nicht.
Die Suche durchsucht auch entschlüsselte Kanaltexte, die in der Datenbank im
Klartext liegen. Es gibt zunächst keine automatische Löschung oder Größenbegrenzung.
Für ein einfaches Backup den Monitor sauber stoppen und die Datenbankdatei kopieren;
bei laufendem Betrieb die SQLite-Backup-Funktion verwenden, nicht nur die Hauptdatei.

Gültig signierte ADVERTs speichern Public Key, Namen und erste/letzte Empfangszeit
in `nodes`. Nur neuere Advert-Zeitstempel aktualisieren den Namen. Nach dem Commit
werden Namen für folgende Pakete aufgelöst: manuelle `ALIASES` zuerst, danach ein
passender eindeutiger Public-Key-Präfix aus SQLite. Ein-Byte-Hashes und mehrdeutige
Präfixe bleiben unaufgelöst. Die Signaturprüfung folgt
[MeshCore Mesh.cpp](https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp).
Die Datenbank samt WAL/SHM-Dateien wird von Git ignoriert. Bestehende Live-Pakete aus
der Zeit vor der Umstellung werden nicht nachträglich importiert.

Im Bereich **Nodes** nach Namen oder einem Teil des Public Keys suchen, ohne
Beachtung der Groß-/Kleinschreibung. Eine leere Suche zeigt alle gespeicherten Nodes,
sortiert nach Public Key, mit jeweils 50 Treffern pro Seite. Jeder Node erscheint
einmal mit seinem aktuellen gespeicherten Namen, vollständigem Public Key und
erster/letzter ADVERT-Empfangszeit in lokaler Zeit. Diese Zeiten sind kein Online-Status.
Neue Einträge sind nach dem nächsten Datenbank-Commit suchbar. Die Suche ist auch
über `GET /api/nodes?q=…` verfügbar; `next_after` dient als `after` für die Folgeseite.

## Aufbau und Prüfung

### Öffentlicher Betrieb: lesende Schnittstellen

Die HTTP-Routen lesen Archivdaten bzw. liefern statische Dateien und Kanalnamen.
Es gibt keine POST-/PUT-/PATCH-/DELETE-Routen und keinen MQTT-Publish- oder
MeshCore-Sendepfad im Anwendungscode. Die SQLite-Schreibpfade werden durch den
internen MQTT-Empfang angesteuert, nicht durch Besucheranfragen.

`/ws` ist auf Anwendungsebene ein reiner Server-Datenstream. Eine eingehende
Text- oder Binärnachricht, auch eine leere, beendet die betreffende Verbindung
mit Code `1008` und Grund `Server-only stream`. Client-Inhalte werden weder
interpretiert noch weitergeleitet oder gespeichert. Der Empfangspfad bleibt
für das Erkennen von Verbindungsabbrüchen und das Abweisen solcher Nachrichten
erhalten; WebSocket ist auf Transportebene weiterhin bidirektional.

nginx `limit_except GET { deny all; }` begrenzt HTTP-Methoden (GET schließt dabei
HEAD ein), aber keine WebSocket-Nachrichten nach dem Upgrade. Die Abweisung
erfolgt deshalb zusätzlich im Backend. Siehe die nginx-Dokumentation zu
[limit_except](https://nginx.org/en/docs/http/ngx_http_core_module.html#limit_except)
und [WebSocket-Proxying](https://nginx.org/en/docs/http/websocket.html).

Die Tests prüfen Client-Daten einschließlich leerer Text-/Binärnachrichten,
Close-Code, Listener-Cleanup, ausbleibende MQTT-Aufrufe und Archiv-Einträge sowie
die Ablehnung schreibender HTTP-Methoden. Snapshot und Live-Updates werden
ebenfalls geprüft. Dies ist eine Prüfung des Anwendungscodes; nginx-,
WireGuard-, Firewall- und Broker-ACL-Konfiguration sind damit nicht verifiziert.

- `onair_mqtt.py`: unveränderter Raw-Decoder, `Packet`-Dataclass, Terminal und MQTT.
- `onair_channels.py`: lokale Kanalkonfiguration und GRP_TXT-Entschlüsselung.
- `onair_advert.py`: ADVERT-Decoder mit Signaturprüfung.
- `onair_archive.py`: SQLite-Speicherung, Namensauflösung und Archivsuche.
- `onair_web.py`: FastAPI-Lebenszyklus, begrenzter Gruppenspeicher, WebSocket.
- `static/`: lokale Webseite ohne CDN oder Build-Schritt.
- `tests/test_onair.py`: Decoder, Aliasgrenzen, Wiederholungen, ungültige Eingaben,
  Speichergrenzen sowie HTTP/WebSocket mit simuliertem MQTT-Client.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Der Tab **Repeater** zeigt direkt empfangene Sender mit horizontalem RSSI-Balken,
Minimum/Maximum, letzter lokaler Empfangszeit und Gesamtzahl der Empfänge.
Angezeigt werden nur Repeater, die in den letzten acht Stunden empfangen wurden.
Nach acht Stunden ohne Empfang verschwinden sie bei der nächsten Aktualisierung;
bei erneutem Empfang erscheinen sie wieder. Gesamtzähler, Min/Max und gespeicherte
Verläufe beziehen sich weiterhin auf das gesamte Archiv.
Gezählt werden letzte Hops von RX-Flood-Paketen (auch TC_FLOOD) und gültig
signierte Repeater-ADVERTs ohne Hop. Zielrouten (DIRECT/TC_DIRECT) werden nicht
als Senderpfad ausgewertet. Wiederholungen zählen als einzelne Empfänge;
fehlende RSSI-Werte zählen mit, verändern aber Min/Max nicht.

Die Statistik liegt dauerhaft in SQLite; vorhandene Archivdaten werden beim
ersten Start nach dem Update einmalig übernommen. `/api/repeaters` liefert die
Übersicht, der sichtbare Tab lädt sie alle fünf Sekunden nach (zuzüglich der
Archiv-Schreibverzögerung). „Ansicht pausieren“ pausiert auch diese Anzeige.
Die Balkenskala reicht von −140 bis −20 dBm, Werte außerhalb werden nur grafisch
begrenzt. Die Zahlen bleiben unverändert. Im Repeater-Tab werden passende
1-, 2- und 3-Byte-Hop-Präfixe anhand längerer empfangener Kennungen und
gespeicherter Nodes zusammengefasst, wenn die Zuordnung unter den bekannten
Kennungen eindeutig ist. Dafür ist kein ADVERT erforderlich. Zähler und Min/Max
werden kombiniert, RSSI und Empfangszeit stammen vom neuesten Empfang.
Mehrdeutige Hashes bleiben separat. Die einzelnen Hash-Statistiken bleiben in
SQLite erhalten, sodass später erkannte Kollisionen wieder getrennt angezeigt
werden können. Die Aliasauflösung in der Paketansicht bleibt unverändert.

Repeater-Zeilen lassen sich aufklappen und zeigen einen RSSI-Verlauf aus dem
Archiv: letzte Stunde, 24 Stunden (Standard), sieben Tage oder gesamtes Archiv.
Je Verlauf werden maximal die neuesten 500 Messwerte im gewählten Zeitraum
angezeigt; eine Begrenzung wird ausdrücklich angezeigt. Fehlende RSSI-Werte
werden ausgelassen. Punkte zeigen echte Empfänge, die Verbindungslinien dienen
der Orientierung. Maus, Touch oder Tastatur zeigen Empfangszeit und RSSI.
Offene Verläufe werden automatisch aktualisiert und berücksichtigen dieselbe
Hash-Zusammenfassung wie die Übersicht. `/api/repeater-history` ist der zugehörige
Lese-Endpunkt. Beim ersten Start wird automatisch eine indizierte Hop-Zuordnung
in der Pakettabelle ergänzt und aus vorhandenen Archivdaten befüllt (Schema 4).

Der Tab **Map** zeigt alle bekannten Nodes mit letzter bekannter Position auf
OpenStreetMap: Repeater als Funkturm (grün), RoomServer als drei Figuren
(orange), Companions als Handfunkgerät (magenta) und weitere Typen als Raute
(violett). Die Symbole haben einen weißen Hintergrund und eine Größe von 36 Pixeln.
Repeater sind als `Funkfeuer [dd42cf]` beschriftet; die sechs Hex-Zeichen sind
die ersten drei Bytes des Public Keys. Ab Zoom 12 erscheinen die Labels in
normaler Größe, bei Zoom 10–11 kleiner und unter Zoom 10 bleiben nur die Icons.
Die Details sind bei jeder Zoomstufe erreichbar. Maus oder
Tastaturfokus zeigen Details, Klick/Touch öffnet ein Popup mit Public Key,
Koordinaten, Zeitpunkt der Position und erster/letzter Empfangszeit.
Nodes ohne Position oder mit dem exakten Koordinatenpaar 0/0 werden gezählt,
aber nicht auf der Karte eingezeichnet. Nodes, deren letzter Empfang mindestens
28 Tage zurückliegt, werden ebenfalls ausgeblendet und separat gezählt.
Maßgeblich ist `last_seen`, also der letzte Empfang eines gültig signierten ADVERTs.
Alle Einträge bleiben in der Datenbank; bei erneutem Empfang erscheinen Nodes
mit bekannter Position wieder auf der Karte.
Nodes mit exakt gleichen Koordinaten werden mit festem Bildschirmabstand
untereinander angeordnet, damit Symbole und Repeater-Beschriftungen einzeln
erreichbar bleiben. Verbindungslinien zeigen ihren tatsächlichen Standort;
die Koordinaten in den Details bleiben unverändert. Beim Zoomen und bei
Aktualisierungen wird die Anordnung automatisch angepasst.

`/api/map-nodes` liefert die innerhalb der letzten 28 Tage gehörten Nodes mit
Position ungleich 0/0 ohne Seitengrenze. `inactive` zählt ausgeblendete alte Nodes,
`without_position` die übrigen Nodes ohne nutzbare Position. Gültig
signierte ADVERTs bestimmen Typ und Position; ältere Positionsmeldungen
überschreiben keine neueren. ADVERTs ohne Koordinaten lassen die letzte bekannte
Position bestehen. Beim ersten Start werden die zusätzlichen Node-Felder aus
dem bestehenden Archiv befüllt (Schema 5). Die Anzeige aktualisiert sich alle
fünf Sekunden und berücksichtigt „Ansicht pausieren“. Der Kartenausschnitt
startet bei Wolfenbüttel mit Zoom 10 und bleibt bei Updates erhalten;
„Alle Nodes anzeigen“ passt ihn an das gesamte Netz an.

Leaflet 1.9.4 wird inklusive Lizenz lokal unter `static/vendor/leaflet/`
ausgeliefert, ohne CDN oder Build-Schritt. Nur die Kartenkacheln werden beim
Öffnen des Map-Tabs direkt von `tile.openstreetmap.org` geladen und benötigen
eine Internetverbindung. Quellen: [Leaflet-Dokumentation](https://leafletjs.com/reference.html)
und [OpenStreetMap-Kachelrichtlinie](https://operations.osmfoundation.org/policies/tiles/).

### Observer Comparison · Ost / West

Der zusätzliche Tab **Observer / Ost–West** vergleicht zwei auswählbare Empfangsstationen.
Die MQTT-Felder `origin_id` (stabile technische Kennung) und `origin` (Anzeigename)
werden pro RX-Empfang im Paket-JSON und als eigene Archivspalten gespeichert.
Gleiche Namen verbinden keine Stationen; eine Namensänderung bei gleicher ID erzeugt
keine neue Station. Ost und West werden im Tab explizit ausgewählt und die Auswahl
wird lokal im Browser gespeichert.

Die Tabelle zeigt je Node und Observer den besten SNR, besten RSSI, letzten lokalen
Empfang und die RX-Anzahl über das gesamte Archiv. Filter: nur Ost, nur West oder
beide. Die Bestwerte werden unabhängig ermittelt und können aus verschiedenen
Empfängen stammen. Es gibt keine Gewinnerwertung. Der Tab aktualisiert sich alle
5 Sekunden; neue Daten erscheinen nach dem nächsten Archiv-Commit.

Die Funkwerte gelten für den unmittelbaren Sender: letzter Hop eines Flood-Pakets
oder Absender eines direkt empfangenen, gültig signierten ADVERTs (alle Node-Typen).
DIRECT-Zielpfade, frühere Hops und Absender weitergeleiteter ADVERTs erhalten keine
fremden Funkwerte. Bekannte Aliase und eindeutig auflösbare Hop-Präfixe werden wie
bisher genutzt; mehrdeutige Kennungen bleiben separat.

Paketgruppen bleiben nach `hash` gruppiert. Jeder Empfang bleibt eine eigene
Archivzeile, auch bei identischem `hash` **und** identischer `origin_id`. Die neue
aggregierte Tabelle `observer_receptions` zählt diese Zeilen und ersetzt sie nicht.
Observer stehen in den Empfangsdetails von Live, Channels und Archiv sowie in der
Live-Liste der wiederholten Empfänge. Die bestehende Live-Tabellenstruktur bleibt erhalten.

Beim nächsten Start migriert das Archiv automatisch über Schema 6 (Observer) und Schema 7 (Noise Floor) und baut die
Observer-Statistik aus vorhandenen Paketen auf. Historische Empfänge ohne
`origin_id` bleiben unzugeordnet, werden separat gezählt und gehen nicht in die
Ost-/West-Zuordnung ein. Fehlende Messwerte erscheinen als „—“, fehlende Empfänge
als „nicht gesehen“. Die Abfrage `GET /api/observer-comparison` liefert Observer
und Node-Statistiken einschließlich ihrer technischen Kennungen. Eine spätere
Observer-Markierung auf Karte oder Topologie kann darauf aufbauen.

Gezielte Regressionstests für den Observer-Vergleich:

```bash
.venv/bin/python -m unittest discover -s tests -p test_observers.py -v
deno run --allow-read=static/observers.js tests/test_observers_ui.js
```

Der JavaScript-Test prüft Darstellung und Filter mit einem kleinen DOM-Testmodell;
er ersetzt keine visuelle Browserprüfung.

Noise-Floor-Regressionstests (Trennung, Migration, Neustart und Step-Kurven):

```bash
.venv/bin/python -m unittest discover -s tests -p test_noise_observers.py -v
deno run --allow-read=static/noise.js tests/test_noise_ui.js
```
