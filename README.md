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

Broker und Topic lassen sich über `ONAIR_MQTT_HOST`, `ONAIR_MQTT_PORT` und
`ONAIR_MQTT_TOPIC` einstellen; Vorgaben sind `192.168.88.40:1883` und
`meshcore/#`. Der Monitor subscribiert ausschließlich; er publiziert nichts und
ändert weder Observer noch BSMesh. Jede Instanz hat eine eigene MQTT-Client-ID.
Der Webmodus versucht bei Ausfällen automatisch die Verbindung wiederherzustellen.
Die Kopfzeile unterscheidet MQTT-Ausfall und WebSocket-Ausfall.

## Docker

Voraussetzung: Docker mit Compose. Im Projektverzeichnis:

```bash
cp -n .env.example .env
# .env öffnen und bei Bedarf Broker, Topic und Webport anpassen.
# Nur falls channels.json noch nicht existiert: leere Kanalliste anlegen.
test -e channels.json || printf '{}\n' > channels.json
docker compose up -d --build
```

Im Browser **http://localhost:8083** öffnen (auf anderen Geräten die IP des
Docker-Hosts verwenden). `ONAIR_HTTP_PORT` ändert den veröffentlichten Port.
Der MQTT-Broker muss aus dem Container erreichbar sein; `localhost` bezeichnet
dort den Container selbst. Für einen Broker auf dem Host dessen LAN-IP verwenden.
Compose liest `.env`; beim direkten Python-Start die Variablen im Shell-Environment setzen.

Mit `ONAIR_SHOW_TX=true` in `.env` erscheinen auch über MQTT gemeldete
`direction: "tx"`-Pakete in Terminal bzw. Docker-Logs. Aktivierende Werte sind
`1`, `true`, `yes` und `on` (Groß-/Kleinschreibung egal); standardmäßig ist die
Anzeige aus. Webansicht und Archiv nehmen weiterhin nur RX-Pakete auf.
Nach der ersten Installation dieser Änderung `docker compose up -d --build`
ausführen; spätere Änderungen der Einstellung mit `docker compose up -d` übernehmen.
Die Ausgabe lässt sich mit `docker compose logs -f onair` verfolgen.

Das Image läuft als Benutzer ohne Root-Rechte mit genau einem Uvicorn-Worker.
`channels.json` wird schreibgeschützt eingebunden. Nach Änderungen daran
`docker compose restart onair` ausführen; bei Änderungen an `.env`
`docker compose up -d` verwenden. Ohne zusätzliche Kanaleinträge ist Public verfügbar.
Die lokale Datenbank, Kanalschlüssel und `.env` werden nicht ins Image kopiert.
Zeitstempel im Container verwenden standardmäßig UTC.

SQLite liegt im persistenten Docker-Volume `onair-data` unter `/data/onair.sqlite3`.
Beim ersten Docker-Start entsteht ein **neues, leeres Archiv**; die vorhandene
`onair.sqlite3` im Projektverzeichnis wird nicht automatisch übernommen.
`docker compose down` erhält das Volume; `docker compose down -v` löscht es
einschließlich des Archivs.

```bash
docker compose logs -f onair       # Webserver- und MQTT-Ausgabe
docker compose ps                 # Containerzustand und HTTP-Healthcheck
docker compose down               # sauber stoppen, Archiv behalten
docker compose up -d --build       # nach Codeänderungen neu bauen und starten
```

Der Healthcheck prüft die HTTP-Erreichbarkeit. Den MQTT-Verbindungsstatus zeigt
die Weboberfläche; ein Broker-Ausfall verhindert den Webstart nicht.

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

Zeit | Typ | Route | Scope | Inhalt | Last Hop / Pfad | RSSI | SNR | Hops | Hash / Empfänge

**Last Hop / Pfad** zeigt die Hop-Kette mit verfügbaren Namen und Hashes.
Bei DIRECT/TC_DIRECT ist dies der verbleibende Weiterleitungspfad; der erste
Eintrag ist als nächster Hop markiert. Bereits durchlaufene Hops und der letzte
Sender sind daraus nicht bestimmbar, daher steht Last Hop auf `Unbekannt`.
Ein leerer Restpfad bestätigt weder einen ursprünglichen Zero-Hop-Versand noch
den Empfang am Ziel. FLOOD zeigt den aufgezeichneten Empfangspfad.
Die aufgeklappten Details zeigen den jeweiligen Pfad jedes einzelnen Empfangs.
TRACE bleibt separat, da sein Pfadfeld SNR-Messwerte enthält.

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
Dasselbe Paket an Observer A und B ergibt zwei Empfänge, auch bei nur einer Aussendung.
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
- `onair_payload.py`: sichtbare Peer-Header, ACK-/Multipart-ACK-Details, TRACE und CONTROL-Discovery.
- `onair_archive.py`: SQLite-Speicherung, Namensauflösung und Archivsuche.
- `onair_web.py`: FastAPI-Lebenszyklus, begrenzter Gruppenspeicher, WebSocket.
- `static/`: lokale Webseite ohne CDN oder Build-Schritt.
- `tests/test_onair.py`: Decoder, Aliasgrenzen, Wiederholungen, ungültige Eingaben,
  Speichergrenzen sowie HTTP/WebSocket mit simuliertem MQTT-Client.

```bash
.venv/bin/python -m unittest discover -s tests -v
```

PATH, REQ, RESPONSE, TEXT_MSG und ANON_REQ zeigen in der Live-Ansicht, im
aufgeklappten Paket und im Archiv die sichtbaren Ziel-/Absender-Hashes (bei
ANON_REQ den Absender-Public-Key), den ungeprüften MAC und den Chiffretext.
Die 1-Byte-Hashes identifizieren Nodes nicht eindeutig. PATH ist eine
Pfad-Rückgabe: Der zurückgemeldete Pfad und mögliche eingebettete ACKs sind
verschlüsselt, ebenso Request-Typ und REQ-Inhalt. Dafür wäre der gemeinsame
Schlüssel der beteiligten Nodes nötig; `channels.json` entschlüsselt diese
Peer-Pakete nicht. Der sichtbare Routing-Pfad bleibt separat dargestellt.
ACKs zeigen den Bestätigungs-Hash in Wire-Reihenfolge und als Little-Endian-Wert;
Multipart-ACKs zusätzlich die Anzahl weiterer Pakete. Alte Archivpakete werden
beim Lesen ergänzt, ohne die gespeicherten Daten umzuschreiben.
Protokollgrundlage: [MeshCore Mesh.cpp](https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp).

CONTROL zeigt Node-Suchanfragen (`DISCOVER_REQ`) mit Typfilter, gewünschter
Public-Key-Länge, Discovery-Tag und optionaler Zeitbegrenzung. Suchantworten
(`DISCOVER_RESP`) zeigen Node-Typ, Public Key oder 8-Byte-Präfix sowie den SNR
der Suchanfrage beim antwortenden Node. Diese Discovery-Daten sind unverschlüsselt;
ein Channel-Schlüssel ist nicht erforderlich. Die Details erscheinen auch in
Rohdaten, Terminal und bestehenden Archivpaketen. Unbekannte CONTROL-Untertypen
bleiben als Hexdaten sichtbar; unvollständige Inhalte werden gekennzeichnet.
Format: [MeshCore Control data](https://github.com/meshcore-dev/MeshCore/blob/main/docs/payloads.md#control-data).

TRACE zeigt Tag, ungeprüften Auth-Code, Flags und die angefragte Route mit
1-, 2-, 4- oder 8-Byte-Hashes. Der äußere Paketpfad enthält hier SNR-Werte
(vorzeichenbehaftete Viertel-dB), keine Node-Hashes. Die Details ordnen jedem
Routen-Hop seinen bereits gesammelten SNR zu; noch ausstehende Messungen bleiben
kenntlich. Der letzte Sender wird nicht aus diesen Messwerten abgeleitet.
Die unverschlüsselten Details erscheinen in Liveansicht, Terminal, Rohdaten und
auch beim Lesen alter Archivpakete. Ein Channel-Schlüssel ist nicht nötig.
Unvollständige Inhalte und nicht unterstützte Flags werden gekennzeichnet.
Format: [MeshCore TRACE-Implementierung](https://github.com/meshcore-dev/MeshCore/blob/main/src/Mesh.cpp).

Der Tab **TRACE** wertet archivierte TRACE-Empfänge für eine Stunde, 24 Stunden
oder sieben Tage aus und aktualisiert sich alle zehn Sekunden. Die Chronik
gruppiert gleiche Tags, Auth-Codes, Routen und Scopes in festen 60-Sekunden-Fenstern.
Sie zeigt bekannte Node-Namen (mehrdeutige Präfixe bleiben markiert), beteiligte
Observer, gemessene Hops sowie SNR-Minimum und -Maximum je Hop. Der niedrigste
beobachtete SNR wird mit seiner Hop-Position hervorgehoben. Diese passive
Zuordnung ist kein eindeutiger Nachweis einer zusammengehörigen Messung.

Für jede Route gibt es einen **SNR-Verlauf über mehrere Messgruppen**. Jeder
Punkt zeigt das Minimum eines Hops innerhalb einer Gruppe; per Maus, Klick oder
Tastaturfokus erscheinen Zeitpunkt und Wertebereich. Wiederholte Empfänge
derselben Gruppe erzeugen keine zusätzlichen Messpunkte. Fehlende Messwerte
unterbrechen die Linien und belegen keinen Routenausfall. Auch vollständig
gesammelte Hop-Werte bestätigen keinen Empfang am endgültigen Ziel.

`GET /api/traces?hours=24&limit=100` liest höchstens 5000 TRACE-Empfänge,
liefert höchstens 100 Chronikgruppen und 100 Routenverläufe mit jeweils den
neuesten 200 Messgruppen. Die Oberfläche zeigt erreichte Grenzen an.
Die Auswertung unterstützt alte Archivpakete ohne Datenmigration.

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_trace.py'
deno run --allow-read=static/trace.js tests/test_trace_ui.js
```

Der Tab **Rohdaten** zeigt die RX-Pakete mit derselben Formatierung wie im
Terminal, einschließlich einzelner Wiederholungen. Die letzten 500 Empfänge
bleiben im Arbeitsspeicher und werden beim Öffnen oder Wiederverbinden geladen.
Neue Pakete erscheinen unten. „Automatisch mitlaufen“ steuert das Scrollen;
„Ansicht pausieren“ hält auch diese Anzeige an.

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
Archiv: letzte Stunde, drei Stunden, 24 Stunden (Standard), sieben Tage oder gesamtes Archiv.
Jeder Observer erhält eine eigene Kurve mit Legende im gemeinsamen Diagramm;
Messwerte verschiedener Observer werden nicht miteinander verbunden.
Die Zuordnung erfolgt über die vollständige Observer-ID. Ältere Empfänge ohne ID
erscheinen separat als „Unzugeordnet“.
Je Verlauf werden maximal die neuesten 500 Messwerte im gewählten Zeitraum
angezeigt; eine Begrenzung wird ausdrücklich angezeigt. Fehlende RSSI-Werte
werden ausgelassen. Punkte zeigen echte Empfänge, die Verbindungslinien dienen
der Orientierung. Maus, Touch oder Tastatur zeigen Observer, Empfangszeit und RSSI.
Offene Verläufe werden automatisch aktualisiert und berücksichtigen dieselbe
Hash-Zusammenfassung wie die Übersicht. `/api/repeater-history` ist der zugehörige
Lese-Endpunkt. Beim ersten Start wird automatisch eine indizierte Hop-Zuordnung
in der Pakettabelle ergänzt und aus vorhandenen Archivdaten befüllt (Schema 4).

Der Tab **Map** zeigt außerdem beobachtete Repeater-Nachbarschaften als einblendbare
Verbindungen. Ein Klick auf einen Repeater filtert die Linien auf seine direkten
Nachbarn in beiden Richtungen. Bei aktivierter Checkbox **Repeater-Verbindungen anzeigen**
bleiben nur der ausgewählte Repeater und seine direkten, auf der Karte zuordenbaren
Nachbarn mit Icons und Namen sichtbar; alle anderen Nodes werden ausgeblendet.
Die Namen bleiben dabei auch bei kleiner Zoomstufe sichtbar. Ausschalten der
Checkbox zeigt wieder alle Nodes. Ein Klick auf die freie Karte oder auf **Alle
Verbindungen anzeigen** hebt den Filter auf. Die Auswahl bleibt bei automatischen
Aktualisierungen erhalten; die Checkbox zur Sichtbarkeit der Verbindungen gilt weiterhin.
Die Karte zeichnet die Verbindungen als
Linien mit Richtungspfeilen. Blau bedeutet beide Richtungen beobachtet, Orange
nur eine Richtung beobachtet. Bei sehr kurzen Linien entfallen die Pfeile aus
Platzgründen; die Zähler bleiben per Klick oder Touch verfügbar. Die Linienstärke
wächst mit der Anzahl der archivierten Empfänge. Die
Nachbartabelle im eigenen Tab **Nachbarn** rechts neben **Map** lässt sich nach Name oder Hash durchsuchen und zeigt
auch unaufgelöste Verbindungen, jeweils 100 pro Seite.
Die Spalte **Entfernung (Luftlinie)** sowie die Kartenverbindungen zeigen die
Entfernung in Kilometern aus den zuletzt gespeicherten GPS-Positionen beider
eindeutig zugeordneten Repeater. Fehlende oder ungültige Positionen (einschließlich
0°/0°) erscheinen als **—** und stehen beim Sortieren immer hinten.
Alle Spalten lassen sich per Klick auf die Überschrift sortieren; ein weiterer
Klick kehrt die Reihenfolge um. Die Sortierung gilt über alle gefilterten Seiten
hinweg und bleibt bei automatischen Aktualisierungen erhalten. Standardmäßig
stehen die Verbindungen mit den meisten Empfängen oben.
Die Spalten **A → B** und **B → A** zählen beide Weiterleitungsrichtungen separat;
ein Filter zeigt nur in einer Richtung beobachtete Verbindungen. A → B bedeutet:
erst von A, dann von B weitergeleitet. Einseitige Beobachtung ist kein Beweis für
eine Funk-Einbahnstraße; Verkehr, Routing und Observer-Standorte beeinflussen sie.
Nachbarschaftsdaten werden für den sichtbaren Tab alle 30 Sekunden abgerufen.
Der Server hält einen gemeinsamen Snapshot für 30 Sekunden im Speicher;
gleichzeitige Anfragen lösen keine mehrfachen Berechnungen aus. Suche, Richtungsfilter,
Sortierung und Seitenauswahl der Tabelle laufen auf dem Server; pro Abruf kommen
höchstens 100 Zeilen zurück. Die Karte lädt separat nur Verbindungen mit zwei
bekannten Positionen und überträgt jeden beteiligten Node einmal.
Beide Endpunkte verwenden ETags: Bei unveränderten Daten antworten sie auf
`If-None-Match` mit HTTP 304 ohne Antwortinhalt. Pro Snapshot werden höchstens
64 Antwortvarianten gespeichert. Nachbarpaare und Richtungszähler werden beim
Archivieren pro Schreibbatch zusammengefasst und dauerhaft gespeichert. Die
Snapshot-Berechnung liest nur diese Paare statt sämtliche historischen Pfade
erneut zu dekodieren. Schleifen zählen weiterhin höchstens einmal pro Empfang
und Richtung. Die Auflösung der Roh-Hashes erfolgt beim Snapshot, sodass neue
Nodes, Hash-Kollisionen und Positionsänderungen weiterhin berücksichtigt werden.
Beim ersten Start nach dem Update wird die Paartabelle einmalig aus den vorhandenen
Pfaden aufgebaut (Schema 11); dieser Start kann daher länger dauern. Weitere
Starts verwenden die gespeicherten Zähler. Die Hash-Auflösung
verwendet einen Präfixindex statt paarweiser Vergleiche aller Kennungen. Die
übrige Karten- und Liveaktualisierung behält ihren bisherigen Takt.

Die Auswertung verwendet ausschließlich benachbarte Hops empfangener Flood- und
TC-Flood-Pfade. A–B und B–A zählen als dieselbe Verbindung, höchstens einmal pro
Empfang, auch bei Schleifen. Wiederholungen und Empfänge mehrerer Observer zählen
erneut. Zusätzlich zählt jede Richtung höchstens einmal pro Empfang. Enthält ein
Pfad beide Richtungen, steigen beide Richtungszähler, der Gesamtzähler aber nur
einmal. Die Richtungssumme kann deshalb größer als die Gesamtzahl sein.
Direct-Pfade, TX-Pakete und Selbstverbindungen werden nicht gezählt.
Sender und Observer werden nicht künstlich an den Pfad angehängt. Die Statistik
umfasst das gesamte Archiv und belegt weder aktuelle Erreichbarkeit noch Funkqualität.
Kurze Hashes werden nur bei eindeutiger Zuordnung mit längeren Kennungen bzw.
bekannten Nodes zusammengeführt. Mehrdeutige Hashes bleiben separat; bekannte
Nicht-Repeater werden ausgeschlossen. Kartenlinien benötigen zwei eindeutig
zugeordnete Repeater mit sichtbaren Positionen.

`GET /api/repeater-neighbors/table` liefert `items`, `page`, `total` (gefiltert),
`total_all` und `one_way_total`. Parameter: `q` (maximal 200 Zeichen), `one_way`,
`sort` (`source`, `target`, `forward_count`, `reverse_count`, `direction`, `count`,
`last_seen`, `distance_km`), `descending`, `page` (ab 0), `limit` (1–100).
`GET /api/repeater-neighbors/map` liefert `nodes` als `[id,name]` und `links` als
`[source_index,target_index,count,forward_count,reverse_count,last_seen,distance_km]`
sowie `total` einschließlich nicht auf der Karte zuordenbarer Verbindungen.

Der bisherige Endpunkt bleibt kompatibel: `GET /api/repeater-neighbors` liefert die Verbindungen mit `source`, `target`,
`count`, `forward_count` (source → target), `reverse_count` (target → source),
`first_seen`, `last_seen` und `distance_km` (Luftlinie in Kilometern, sonst `null`). Die Richtungen werden auch aus bereits gespeicherten
Pfaden ausgewertet; dafür ist keine weitere Migration nötig. Schema 9 baut beim nächsten Start einmalig
die Tabelle `repeater_paths` aus dem vorhandenen Archiv auf und aktualisiert sie
danach mit jedem archivierten Empfang. Rohe Pfade bleiben erhalten, damit später
bekannt gewordene Hash-Kollisionen bei der Zuordnung berücksichtigt werden.

### Routenplaner

Der Tab **Routen** sucht Start und Ziel nach Name, Hash oder Public Key. Bei mehreren
Treffern einen eindeutigen Eintrag aus den Vorschlägen auswählen. **Tauschen** kehrt
Start und Ziel um. Die Suche liefert bis zu fünf unterschiedliche, schleifenfreie
Routen, aufsteigend nach Anzahl der Funkstrecken; gleich kurze Alternativen sind
entsprechend markiert. Eine direkte Nachbarverbindung zählt als eine Funkstrecke.
Standardmäßig sind höchstens 32 Funkstrecken erlaubt (einstellbar von 1 bis 64).

Grundlage sind die Repeater-Nachbarn aus dem gesamten Archiv, auch ohne Position.
Einseitig bekannte Verbindungen sind standardmäßig in beiden Richtungen nutzbar.
Jede Strecke zeigt die beobachteten Richtungen, deren Empfangszähler und den letzten
Beobachtungszeitpunkt. Eine nur in Gegenrichtung beobachtete Strecke wird ausdrücklich
markiert. **Nur in Reiserichtung beobachtet** schließt solche Strecken aus.
Die Kilometerangabe summiert die Luftlinien zwischen den Nodes, sofern alle
Positionen bekannt sind; optimiert wird nach Funkstrecken, nicht nach Entfernung.

Mehrdeutige Hashes werden samt ihren Verbindungen ausgeschlossen. Eindeutige, noch
nicht einem bekannten Node zugeordnete Hashes bleiben mit Kennzeichnung nutzbar.
Nodes ohne Nachbarverbindungen und bekannte Nicht-Repeater stehen nicht zur Auswahl.
Die Routen kombinieren einzelne Beobachtungen: Sie müssen nicht als Ganzes empfangen
worden sein und garantieren keine aktuelle Erreichbarkeit. Die Suche verwendet den
gemeinsamen Nachbar-Datenstand (bis zu 30 Sekunden alt); Ergebnisse werden mit
**Routen suchen** neu berechnet. Es werden keine Pakete ins Mesh gesendet.

`GET /api/routes/nodes` liefert die auswählbaren Nodes. `GET /api/routes` akzeptiert
`start`, `target` (Name oder Hash, eindeutig), `observed_only` (Standard `false`),
`limit` (1–5, Standard 5) und `max_hops` (1–64, Standard 32). Unbekannte oder
mehrdeutige Eingaben ergeben HTTP 400, ungültige Parameter HTTP 422; ohne Verbindung
ist `routes` leer. Identischer Start und Ziel ergibt eine Route mit null Funkstrecken.

```bash
.venv/bin/python -m unittest discover -s tests -p test_routes.py -v
deno run --allow-read=static/routes.js tests/test_routes_ui.js
```

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

### Observer-Vergleich · A / B

Der zusätzliche Tab **Observer A / B** vergleicht zwei auswählbare Empfangsstationen.
Die MQTT-Felder `origin_id` (stabile technische Kennung) und `origin` (Anzeigename)
werden pro RX-Empfang im Paket-JSON und als eigene Archivspalten gespeichert.
Gleiche Namen verbinden keine Stationen; eine Namensänderung bei gleicher ID erzeugt
keine neue Station. Observer A und B werden im Tab explizit ausgewählt und die Auswahl
wird lokal im Browser gespeichert.

Die Tabelle zeigt je Node und Observer den besten SNR, besten RSSI, letzten lokalen
Empfang und die RX-Anzahl über das gesamte Archiv. Filter: nur A, nur B oder
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
A-/B-Zuordnung ein. Fehlende Messwerte erscheinen als „—“, fehlende Empfänge
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

Der Tab **Discovery** gruppiert passiv empfangene `DISCOVER_REQ` und
`DISCOVER_RESP` nach Discovery-Tag und Scope innerhalb eines festen
60-Sekunden-Fensters. Die Zuordnung ist eine zeitliche Näherung, kein Nachweis
identischer Suchender. Suchende Nodes werden nicht aus Observern oder Hops
abgeleitet. Antworten ohne mitgehörte Anfrage bleiben sichtbar.

Aufklappbare Gruppen zeigen Suchfilter, Zeitbegrenzung, Observer und antwortende
Nodes mit Public Key, Namen aus der Node-Datenbank und SNR der Suchanfrage beim
antwortenden Node. Wiederholte Antworten derselben Kennung erhöhen den
Empfangszähler; unterschiedliche SNR-Werte erscheinen als Bereich. Eindeutige
8-Byte-Präfixe werden bekannten Public Keys zugeordnet, mehrdeutige bleiben
markiert. Discovery allein erzeugt keine verifizierten Node-Einträge.

Zeiträume: eine Stunde, 24 Stunden oder sieben Tage. Alle zehn Sekunden wird der
sichtbare Tab aktualisiert; die globale Pause gilt auch hier. Die Auswertung
liest vorhandene Archivpakete ohne Migration, höchstens die neuesten 5000
CONTROL-Empfänge im Zeitraum, und zeigt maximal 100 Gruppen. Begrenzungen werden
angezeigt. Fehlende Antworten sind kein Offline-Nachweis. API: `/api/discovery`
mit `hours=1..168` und `limit=1..100`.

### MeshLive · animierte Karte

**MeshLive** ergänzt einen eigenen Tab. Die textbasierte **Live**-Ansicht mit ihren
Filtern, Empfangsdetails und ihrem Pause-Schalter bleibt unverändert. Beide verwenden
denselben `/ws`-Datenstrom; MeshLive öffnet weder einen weiteren WebSocket noch eine
MQTT-Verbindung. Leaflet und Canvas werden erst beim Öffnen des Tabs initialisiert.

Zwei unabhängig schaltbare Darstellungen sind standardmäßig aktiv:

- **Beobachtete Empfänge**, durchgezogen: letzter eindeutig aufgelöster Hop eines
  RX-FLOOD/TC_FLOOD → Observer. Ein gültig signierter ADVERT ohne Hop identifiziert
  seinen unmittelbaren Sender ebenfalls. Die Observer-ID muss exakt einem bekannten
  vollständigen Public Key entsprechen; Namen und kurze Observer-Präfixe reichen nicht.
- **Rekonstruierte Flood-Pfade**, dezent gestrichelt: benachbarte Originaleinträge des
  empfangenen Flood-Pfades. Diese Strecken sind aus dem Paket abgeleitet, keine separat
  am Observer gemessenen Empfänge. Unbekannte Zwischenhops werden niemals überbrückt.

DIRECT/TC_DIRECT-Zielrouten, TRACE-SNR-Pfade und TX bleiben ausgeschlossen. Alle
Teilstrecken eines Ereignisses starten gleichzeitig; die Animation behauptet keine
Hop-Zeitmessungen. Alle Spuren haben dieselbe Farbe. Ein Lichtpunkt bewegt sich
300 ms vom Sender zum Empfänger; die zurückbleibende Spur verblasst anschließend
700 ms. Nach insgesamt 1.000 ms wird die Animation entfernt. Keine dauerhaften
Funkverbindungslinien. Der Livebetrieb spielt keine historischen Ereignisse nach;
der zusätzliche Replay-Modus wird ausdrücklich gestartet (siehe unten).

Die Konstanten stehen am Anfang von `static/meshlive.js`:

| Konstante | Standard | Bedeutung |
| --- | ---: | --- |
| `TRAVEL_MS` | 300 | Bewegung des Lichtpunkts |
| `TOTAL_MS` | 1000 | Gesamtdauer einschließlich Verblassen |
| `MAX_ACTIVE` | 64 | Maximale Zahl gleichzeitig aktiver Spuren |
| `DEDUP_WINDOW_MS` | 10000 | Festes Fenster für Mehrfachbeobachtungen |
| `MAX_DEDUP_ENTRIES` | 5000 | Maximale Zahl gemerkter Streckenereignisse |
| `MAX_DPR` | 2 | Obergrenze der Canvas-Pixeldichte |
| `ACTIVE_DAYS` | 28 | Gleiche Knotensichtbarkeit wie auf der bisherigen Karte |

`TRAVEL_MS` muss positiv und kleiner als `TOTAL_MS` sein. Änderungen am
Deduplizierungsfenster oder Spurenlimit auch in der Kartenhilfe berücksichtigen.

Empfangsnummern verhindern das erneute Verarbeiten derselben WebSocket-Empfänge.
Die anschließende Strecken-Deduplizierung verwendet normalisierten Paket-Hash,
Payload-Typ/-Version/-Inhalt, Transport-Code und das **gerichtete** vollständige
Sender-/Empfängerpaar. Unterschiedliche Pfade oder Observer erzeugen für denselben
Hop keine neue Spur; unterschiedliche Hops desselben Pakets bleiben sichtbar.
Fehlt der Hash, dient der gleiche Inhaltsvergleich als heuristischer Ersatz.
Eine später direkt beobachtete, bereits rekonstruierte Strecke erhält während ihrer
laufenden Animation durchgezogene Darstellung, ohne die Dauer neu zu starten.

Wiederholungen verlängern das feste Zehn-Sekunden-Fenster nicht. Ohne eindeutige
Aussendungskennung sind echte erneute Aussendungen und verspätete Mehrfachmeldungen
nicht perfekt trennbar: Wiederholungen können zusammenfallen, sehr späte Duplikate
erneut erscheinen. Bei ausgeschöpftem Deduplizierungsspeicher werden die ältesten
Einträge verdrängt. Zwei verschiedene Observer-Empfänge derselben Aussendung bleiben
zwei Empfangsbeziehungen; die Ansicht zählt keine physikalischen Aussendungen.

`GET /api/map-nodes?mesh_live=true` liefert nur beim Öffnen, Wiederverbinden oder
manuellen Aktualisieren einen Knotenbestand einschließlich unsichtbarer Identitäten
und bekannter Hop-Kennungen. Damit erzeugen fehlende Positionen oder ausgeblendete
Knoten keine falsche Eindeutigkeit kurzer Präfixe. Neue gültige ADVERTs und
Hop-Kennungen aktualisieren diesen Bestand aus dem Stream; ein verspäteter HTTP-Abruf
überschreibt keine neuere ADVERT-Position. Der bisherige Aufruf ohne Parameter bleibt
unverändert. Keine periodischen Vollabfragen, keine Abfrage der Paketarchivtabelle,
keine Schemaänderung und keine Änderung der Nachbarberechnung.

Positionen stammen aus zuletzt gültig signierten ADVERTs. Fehlende, ungültige,
inaktive oder 0/0-Positionen werden nicht verbunden. Identische Standorte bleiben an
ihren tatsächlichen Koordinaten; Nullstrecken werden übersprungen. Eine im bekannten
Bestand eindeutige Kurzkennung ist kein globaler Identitätsbeweis. Die Signatur eines
ADVERTs bestätigt nicht seine komplette Weiterleitungskette und die Spur zeigt
keinen geografisch gemessenen Funkweg.

**Animation pausieren** wirkt ausschließlich auf MeshLive. Pausieren, Verlassen des
Tabs oder Verbergen des Browserdokuments entfernt laufende Animationen. Währenddessen
eintreffende Ereignisse werden nicht nachgespielt. Initiale und spätere WebSocket-
Snapshots synchronisieren den Stand ohne Animation. Die bestehende Streambegrenzung
(500 Gruppen, 50 Empfänge je Gruppe, begrenzte Queues) kann bei Spitzenlast Ereignisse
auslassen. Zusätzliche Spuren oberhalb des Limits werden ohne Warteschlange verworfen.
Der Status zeigt nicht zuordenbare Streckenkandidaten, verworfene Animationen, den
vorhandenen Server-Verlustzähler und Stream-Abgleiche; diese Werte sind keine
vollständige Funkverluststatistik.

Lokale Tests:

```sh
.venv/bin/python -m unittest discover -s tests -v
deno run --allow-read=static/meshlive.js tests/test_meshlive_ui.js
# Python-Umgebung mit Playwright und lokalem /usr/bin/chromium:
python tests/browser_meshlive.py
# Optional: textbasierte Liveansicht zusätzlich gegen einen Git-Stand vergleichen:
python tests/browser_meshlive.py --compare-ref HEAD
```

Der Browsertest verwendet ausschließlich abgefangene HTTP-Anfragen, simulierte
WebSocket-Ereignisse und lokale Kachelersatzbilder. Er startet weder das Backend
noch MQTT und schreibt nicht in das Archiv. Desktop-/Mobilaufnahmen landen unter
`/tmp/meshlive-desktop.png` und `/tmp/meshlive-mobile.png`. Er prüft insbesondere
Live-Filter, Details, Pause/Fortsetzen, bestehende Tabreihenfolge, getrennte Schalter,
Snapshots, Tabwechsel, Kartenbedienung und Animationsbereinigung. Kein Deployment
ist Teil dieser Tests.

### MeshLive Replay · letzte zehn Minuten mit 10×

Im MeshLive-Tab startet **Letzte 10 Minuten wiedergeben** einen isolierten Replay.
Die Karte trägt gut sichtbar **REPLAY · 10×**. Fortschritt, historischer Zeitpunkt,
**Replay pausieren / fortsetzen** und **Replay beenden** stehen in der Seitenleiste.
Die textbasierte Liveansicht und ihre Filter laufen unverändert weiter.

Replay verwendet einmalig `GET /api/meshlive/replay`, ohne zusätzliche WebSocket- oder
MQTT-Verbindung. Der Server bestimmt ein festes Fenster `[jetzt − 600 s, jetzt)`.
Es werden nur bereits archivierte Empfänge geliefert. Der Archivwriter kann die
letzten Sekunden noch zurückhalten; der angezeigte Archivstand ist keine Zusage
vollständiger Funkbeobachtung. Es gibt keinen erzwungenen Commit und keine Ergänzung
mit Live-Ereignissen.

Die Antwort enthält `window_start`, `window_end`, `speed: 10`, `events` mit Archiv-ID,
`received` und kompaktem Paket sowie `bootstrap` mit Knoten, Kollisionskennungen und
historischen `seed_packets`. Zusätzlich werden `archive_latest_received`,
`seed_adverts_scanned` und `seed_scan_limited` geliefert. Das Zeitfenster und die
Grenzen können nicht über Anfrageparameter vergrößert werden. Die Antwort ist
`Cache-Control: no-store`.

Schutzgrenzen in `onair_replay.py`:

- 5.000 Empfangszeilen; eine weitere Zeile erkennt Überlauf, statt still abzuschneiden.
- Maximal 2.000 untersuchte ADVERT-Zeilen für den Positions-Startbestand. Neuere und
  zu alte Empfänge werden erst **nach** der Begrenzung ausgeschlossen, damit auch bei
  ungewöhnlichen Zeitstempeln keine unbeschränkte Suche entsteht.
- Maximal 4 MiB Antwort, zusätzlich 16 MiB eingelesene Paket-JSONs.
- SQLite-Fortschrittsüberwachung mit drei Sekunden SQL-Zeitbudget.

Ereignis- oder Größenüberlauf liefert HTTP 413 und eine verständliche Fehlermeldung.
Ein nicht lesbares Archiv beziehungsweise SQL-Zeitüberschreitung liefert HTTP 503.
Fehlende historische Positionen führen nur zum Auslassen betroffener Strecken;
begrenzte Positionssuche wird ausdrücklich angezeigt. Keine neue Tabelle, kein
neuer Index, keine Änderung an Nachbarstatistiken. Zeitbereich und Sortierung nutzen
`packets_received`, die begrenzte ADVERT-Suche `packets_kind_id`. Alle SELECTs laufen
in einem gemeinsamen, mit `query_only` geschützten Lesesnapshot.

**Historische Positionen:** Ein Knoten-Snapshot ist nur dann als Startbestand erlaubt,
wenn sein `last_seen` vor dem Fensterbeginn liegt. Bei später gehörten Nodes werden
aktuelle Position, Name und Typ im Replay-Startbestand entfernt. Alle Public Keys
bleiben zur konservativen Kollisionsprüfung erhalten. Für diese Nodes liefern gültig
signierte, früher empfangene ADVERTs aus der begrenzten Suche einen Startbestand,
sofern sie in den vorhergehenden 28 Tagen empfangen wurden. Diese ADVERTs durchlaufen
`MeshLiveModel.learn()` und damit dieselben Positionsregeln wie Live, ohne Animation.
ADVERTs innerhalb des Replay-Fensters werden erst zu ihrem eigenen Empfangszeitpunkt
angewendet. Ein alter Geräte-Zeitstempel allein belegt keinen früheren Empfang.
Fehlende Positionen werden nicht aus späteren Meldungen rückwärts ergänzt. Ein
belegter ADVERT-Stand ist weiterhin kein Nachweis tatsächlicher geografischer Bewegung.

**Getrennte Uhren:** `received` plus Archiv-ID bestimmen Reihenfolge und Gleichstände.
Die Deduplizierung nutzt zehn **historische** Sekunden. Die visuelle Replay-Uhr läuft
in realen Wiedergabemillisekunden und steht während Pause still. Nur Ereignisabstände
werden durch zehn geteilt; Sternschnuppen behalten 300 ms Bewegung und 700 ms Verblassen.
Zeitabstände zeigen die Ankunft bei OnAir, nicht Hop-Laufzeiten. Die Timeline endet
nach 60 Sekunden; letzte Spuren dürfen bis zu einer Sekunde nachglühen. Anschließend
kehrt die Ansicht automatisch zu Live zurück.

`MeshLiveReplay` verwendet eine eigene `MeshLiveModel`-Instanz, dieselbe
Streckenrekonstruktion, denselben Deduplizierungsschlüssel und denselben Canvas-Renderer.
Das Replay beginnt mit leerem Deduplizierungszustand. Es ist keine pixelgenaue
Rekonstruktion der damaligen Liveanzeige: deren Zustand vor Fensterbeginn und mögliche
Transportverluste sind nicht gespeichert. Normale Live-Zeitachsen bleiben unverändert.

Bei Tabwechsel oder verborgenem Browserdokument pausiert Replay automatisch; beim
Zurückkehren muss es ausdrücklich fortgesetzt werden. Auch laufende Spuren behalten
ihren Animationsstand. Während Replay werden eingehende Live-Pakete und Snapshots
niemals in dessen Modell übernommen; nur der Live-Empfangsfortschritt wird aktualisiert.
Beim Beenden wird der Replay-Zustand verworfen und der normale Live-Knotenbestand neu
abgeglichen. Aufgelaufene Live-Pakete werden nicht nachgespielt. Ein bereits vor Replay
pausierter Livebetrieb bleibt pausiert.

Ein gemeinsamer `requestAnimationFrame`-Loop bewegt auch die Replay-Uhr in Verkehrspausen.
`MESH_REPLAY.MAX_PER_FRAME` begrenzt die Verarbeitung auf 200 Empfänge pro Frame;
`FRAME_BUDGET_MS` begrenzt sie zusätzlich auf acht Millisekunden. Die vorhandenen
Grenzen von 64 aktiven Spuren und 5.000 Deduplizierungseinträgen bleiben bestehen.
Nach einem Browserstillstand bereits abgelaufene Spuren werden nicht verspätet
abgespielt; die ausgelassenen Empfänge werden angezeigt. Es gibt keine Timer pro Paket.

Zusätzliche lokale Tests:

```sh
.venv/bin/python -m unittest discover -s tests -p test_replay.py -v
deno run --allow-read=static/meshlive.js tests/test_replay_ui.js
# Python-Umgebung mit Playwright und lokalem Chromium, ausschließlich simulierte Daten:
python tests/browser_replay.py
python tests/browser_meshlive.py --compare-ref HEAD
```

Der Replay-Browsertest verwendet eine kontrollierte Browseruhr. Er prüft die komplette
60-Sekunden-Timeline samt Nachglühen, eingefrorene Spuren, Live-/Snapshot-Isolation,
Tabwechsel und Sichtbarkeit, HTTP-Limits, leere Fenster, verspätete Antworten nach
Abbruch sowie Desktop-/Mobilbedienung. Screenshots liegen unter
`/tmp/meshlive-replay-desktop.png` und `/tmp/meshlive-replay-mobile.png`.
