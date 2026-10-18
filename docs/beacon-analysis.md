# MeshCore Beacon und MeshCore OnAir – Quellcodeanalyse

Stand: 18. Oktober 2026. Ergebnis eines reinen Analyseauftrags; keine Implementierungsentscheidung.

## Untersuchungsgrundlage und Aussagegrenzen

Untersucht wurden die vier öffentlich sichtbaren Repositories der [Organisation MeshCore-Beacon](https://github.com/MeshCore-Beacon) sowie die von Beacon fest eingebundene Decoder-Version `meshcore-go v1.0.8`. Die Repositories wurden nach `/tmp/beacon-analysis` geklont. OnAir wurde im vorhandenen Arbeitsbaum gelesen. Die unten verlinkten Beacon-Fundstellen sind auf Commit-Hashes fixiert; OnAir-Verweise beziehen sich auf den ebenfalls festgehaltenen lokalen Stand.

**Kennzeichnung:** **I** = im Quellcode implementiert; **D** = dokumentierte Absicht oder Beschreibung; **S** = Schlussfolgerung/Bewertung aus dem Code. Negativbefunde bedeuten „in den untersuchten relevanten Datenwegen nicht vorhanden“, nicht den Beweis, dass es nirgendwo experimentellen Code gibt.

**Methode und Grenzen:** Statische Analyse von Ingestion, Decoder, Schema, SQL, API, Hintergrundjobs und Webkomponenten; vorhandene Tests ergänzend gelesen. Keine Dienste gestartet, keine Abhängigkeiten installiert, keine Datenbanken geöffnet oder migriert und keine Lasttests ausgeführt. UI/UX ist eine Bewertung implementierter Bedienabläufe, kein Browser- oder Smartphone-Praxistest. Durchsatz, RAM-Bedarf, reale Paketverluste und Produktionskonfigurationen wurden nicht gemessen. Die Flutter-App wurde zur Rollen- und Technologieeinordnung untersucht, nicht vollständig auf Funktionsparität geprüft. Nur dieses Dokument wurde im OnAir-Projekt angelegt.

### Fixierte Versionen

| Projekt | Commit |
|---|---|
| beacon-server | `202acc6cc8f616819a3577c57a7009ea1a48c0dd` |
| beacon-web | `bd5b8951e4a30976e84efd8348c14597a962e50e` |
| beacon-docs | `9de500cfa5be98f4d8affe68aae68d2631750d73` |
| beacon-flutter-app | `15e6f514ce188a74bf7d792da9024a307a275153` |
| meshcore-go | `427ab2cc863ebd7aa2f502d93c09c7268059ec01` |
| OnAir | `d567222a79260616d4cb58b4b8ed5490cb30f2b2` |


Alle vier Beacon-Repositories enthalten eine AGPL-v3-Lizenzdatei; Server-Quelldateien und das Webpaket kennzeichnen überwiegend `AGPL-3.0-or-later`. Es wurde **kein Code übernommen**. Vor einer späteren Übernahme wäre die Lizenzverträglichkeit der konkreten Dateien einschließlich Fremdanteilen separat zu prüfen. Die Empfehlungen beschreiben Anforderungen, keine Freigabe zur Codeübernahme.

## 1. Zusammenfassung der Beacon-Architektur

### Repositories und Rollen

| Repository | Funktion und untersuchter Umfang |
|---|---|
| `beacon-server` | Go-Backend: MQTT, Protokolldekodierung, PostgreSQL, REST, WebSocket, Redis-Cache, Hintergrundjobs und Backup-Export. Hauptgegenstand der Datenanalyse. |
| `beacon-web` | React-/TypeScript-Webanwendung mit Vite, TanStack Query/Virtual, MapLibre und ECharts. Hauptgegenstand der UX-Analyse. |
| `beacon-docs` | Architektur- und API-Dokumentation sowie Compose-/Proxy-Konfigurationen. Kein zusätzlicher Analyse-Backenddienst. |
| `beacon-flutter-app` | Nativer Dart-/Flutter-Client für iOS/Android; laut README dieselbe REST-/WS-Schnittstelle, kein eingebauter Server. `pubspec.yaml` bestätigt u. a. MapLibre Native und Diagrammbibliothek. |

Quellen: [B01], [B02], [B03], [B04].

### Implementierter Datenfluss

1. **MQTT:** Das Serverprogramm erzeugt konkret zwei Broker-Worker (`mqtt1`, `mqtt2`); Observer werden über Public Keys identifiziert, Empfangsgebiete über IATA-Codes. „Mehrere Broker“ ist damit belegt, eine beliebig große dynamische Brokerliste nicht. Je Worker gibt es acht Verarbeitungsspuren mit je 2.048 Queue-Plätzen und zusammen 32 MiB Nutzdaten-/Topic-Budget. Observerbezogenes Hashing hält die Reihenfolge innerhalb eines Workers; es ist keine globale Reihenfolge über beide Broker. Volle Queues verwerfen Meldungen und protokollieren die Anzahl. [B05], [B06]
2. **Decoder:** `meshcore-go v1.0.8` liefert Packet-/Payload-Parser. Beacon bereitet typisierte JSON-Payloads auf, prüft ADVERT-Signaturen vor Node-Aktualisierungen und entschlüsselt bekannte Gruppenkanäle. Der Empfang enthält Observer-Radioinformationen, RSSI/SNR, Pfad, Zeit und Brokerherkunft. [B01], [B07], [B08]
3. **Persistenz:** Ein logisches Paket liegt in `packets`; die Beobachtungen liegen separat in `packet_observations`. `nodes.public_key` ist eindeutig. `node_short_ids` hält regionale Präfixzuordnungen, `known_routes` vollständig aufgelöste Pfade, `node_neighbors` aggregierte Nachbarschaften. Zusätzlich existieren Observer-Telemetrie/-Positionen, TRACE-Tag-Summen und Stundenaggregate. [B09], [B10]
4. **Abfragen:** Chi stellt `/api/v1/packets`, `/nodes`, `/observers`, `/routes`, `/traces`, `/stats` usw. bereit. Listen nutzen serverseitige Filter und überwiegend Cursor. Der WS-Hub filtert vor dem Fan-out nach Region/IATA, Observer, Payload-/Route-/Event-Typ und Kanal. Langsame Clients erhalten eine Verlustmeldung, statt die Ingestion zu blockieren. [B11], [B12]
5. **Betrieb:** Das dokumentierte Komplettdeployment hat fünf Dienste: Anwendung, PostgreSQL 16, Redis 7, Caddy und Webfrontend. Redis beschleunigt Leseabfragen, fällt bei Fehlern auf Datenbankabfragen zurück und ist in diesem Datenweg kein verteilter Eventbus. Stunden-Rollups und Retention werden im Backend ausgeführt. [B03], [B13], [B14]

**S:** Die Skalierbarkeit entsteht wesentlich aus begrenzter Arbeit, gezielten Indizes, deduplizierter Speicherung, Voraggregation und gefilterter Auslieferung. Go und PostgreSQL allein beweisen keinen Durchsatzvorteil. Der WS-Hub ist pro Prozess im Speicher; ein vollständig koordinierter, horizontal skalierter Live-Cluster ist damit nicht nachgewiesen.

### Dokumentierte Absicht versus implementiertes Verhalten

| Dokumentation/Bezeichnung | Quellcodebefund | Einordnung |
|---|---|---|
| **D:** High-Level-Design beschreibt eine breitere Auflösung über die IATAs einer ausgewählten Großregion | **I:** `ResolvePathHashes` nimmt genau ein IATA; TRACE kombiniert mehrere Einzelresultate nach Konfidenzrang | Nicht mit einer gemeinsamen Kandidatenunion verwechseln; siehe Abschnitt 4. |
| **D:** Die Designregel verlangt für Kartenpfade ausschließlich eindeutige Hops | **I:** Die aktuelle Webfunktion erhält bekannte Teilstücke und setzt Unterbrechungen an unsicheren Hops | Sinnvolle Weiterentwicklung; die vollständige Designbeschreibung ist nicht identisch mit dem aktuellen Rendering. |
| **D:** TRACE-Summary beschreibt die vollständigste Beobachtung | **I:** Die SQL-Auswahl maximiert die Anzahl angefragter Hashes, nicht die Zahl gemessener SNRs | Für fortschreitende Messungen derselben Route relevant; siehe Abschnitt 3. |
| **D:** Kandidaten zeigen statt Identitäten raten | **I:** Präfix-/IATA-Resolver ohne Wahrscheinlichkeitsscore | Grundsätzlich bestätigt; das Label `high` und der TRACE-Merge bleiben erklärungsbedürftig. |

Quellen: [B10], [B15], [B18], [B21], [B24], [B29].

## 2. Vergleichstabelle Beacon / OnAir

| Aspekt | Beacon – implementiert | OnAir – implementiert | Bewertung |
|---|---|---|---|
| Laufzeit/Betrieb | Go, Chi, pgx/sqlc, PostgreSQL; optionaler Cache-Datenweg über Redis; separates Frontend | Python, FastAPI/Uvicorn, Paho; SQLite; statische JS-/CSS-Dateien | OnAir hat wesentlich weniger Betriebskomponenten. |
| Observer | Vollschlüssel, IATA-/Brokerzugehörigkeit, Telemetrie, Verzeichnis | `origin_id`, Observervergleich, Empfangs-/Signalstatistik | Beide Multi-Observer-fähig; Beacon regional/brokerübergreifend umfangreicher. |
| Roharchiv | Paket plus höchstens eine gespeicherte Beobachtung je Paket/Observer | Eigene Archivzeile je an Archiv übergebenem Empfang | Unterschiedliche Semantik, keine pauschale Gleichwertigkeit von Zählern. |
| TRACE-Gruppierung | Globaler Tag als Gruppenschlüssel | Tag + Auth-Code + Scope + Flags/Route + 60-s-Fenster | OnAir schützt besser gegen wiederverwendete Tags. |
| TRACE-Verlauf | Tagliste, Paketdetails, Hop-SNR | Messgruppen, SNR-Min/Max je Hop, Zeitverlauf pro Route; Einzelvergleich auf Karte | Für passive Messreihen ist OnAir bereits weiter. |
| DISCOVER | Dekodierung im Paketinspektor; Observer→Responder-Nachbareintrag mit RX-SNR | Eigene Discovery-Chronik, Tag-/Scope-/Zeitgruppierung, verwaiste Antworten | OnAir besitzt den besseren Discovery-Arbeitsablauf; Beacon eine zusätzliche Topologieverwertung. |
| Kollisionsauflösung | Präfix + IATA + Relay-Rolle; Kandidatenlisten | Konservative Auflösung gegen bekannte Identitäten; Rohpräfix bleibt bei Mehrdeutigkeit | Kein probabilistischer Resolver in beiden untersuchten Datenwegen. |
| Nachbarn | ADVERT, TRACE, DISCOVER_RESP, `/neighbors`-Reports; aggregierte Werte | Beobachtete benachbarte Flood-Hops, Richtungszähler, Rohpfade | Mehr Evidenzarten bei Beacon; konsistentere Flood-Richtungsanalyse bei OnAir. |
| Fernstrecken | Zusammensetzen bekannter Routen über Nachbarkanten zwischen IATAs | Historische Distanzanalyse mit Position zum Empfang, Paket-/Empfangszählern und Belegen | Unterschiedliche Aufgaben; Beacon ersetzt OnAirs Fernverbindungsanalyse nicht. |
| Routen | Gespeicherte vollständige Pfade, Endpunktsuche, Cross-IATA-Segmente | Bis zu fünf kürzeste schleifenfreie Kandidaten, optional nur beobachtete Richtung | Beacon ist Pfadkatalog, OnAir zusätzlich Graph-Routenplaner. |
| Historische Positionen | `nodes` mit aktuellem Standort; separate Historie für Observer | ADVERT-basierte Position zum damaligen Empfang in TRACE-/Fernanalyse | OnAir vermeidet dort rückwirkende heutige Geografie. |
| Archivperformance | Stunden-Rollups, Query-Indizes, Redis, Cursor, virtuelle Listen | WAL, ein Batch-Writer, Rohpfad-/Paaraggregate, Indizes, begrenzte Abfragen, lokale Caches | Vieles ist schon vorhanden; Rollups nur bei gemessenem Bedarf. |
| Kontextnavigation | Verlinkte Detailpanels, Paketinspektor, URL-Zustand, mobile Sondernavigation | Aufgabenansichten und Teilverknüpfungen; TRACE/Discovery überwiegend Textgruppen | Beacon liefert gute Vorbilder für kleine UI-Verbesserungen. |

Belege: [B05–B24], [O01–O10]; Details und Einschränkungen in den folgenden Abschnitten.

## 3. TRACE- und DISCOVER-Verarbeitung

### 3.1 TRACE: Tag, Einzelempfang und Route

**I – Beacon:** Der Decoder liest Tag, Auth-Code, Flags und angefragte Hop-Hashes aus der TRACE-Payload; der äußere Pfad enthält signierte SNR-Bytes mit Faktor 1/4 dB. Ein Pfad mit einem Hash wird in der UI als `PING` klassifiziert. Das ist eine Beacon-Klassifikation, kein Beleg für ein separates Request-/Response-Protokoll. [B07]

Die Tabellen `trace_tags` und `trace_iatas` aggregieren nach Tag. Die Detailabfrage `GetPacketsByTraceTag` filtert ausschließlich nach Tag und liefert sämtliche erhaltenen Paketvarianten. Auth-Code, Route, Scope und Session-Zeitfenster grenzen diese Detailgruppe nicht ab. Die Listenfilter für `since/until` beziehen sich auf den ersten Empfang der Taggruppe; der Scope ist der erste übernommene Scope. **S:** Wiederverwendete Tags können über Zeit, Route und Scope hinweg zusammenfallen; ein Listenfilter macht die anschließende Detailgruppe nicht automatisch zu einer entsprechend eingeschränkten Sitzung. [B10], [B15]

**I – OnAir:** `trace_sessions` korreliert nach `(tag, auth_code, scope, flags, route)` innerhalb von 60 Sekunden ab Gruppenbeginn, zählt Empfänge und Observer und sammelt je Hop Min/Max. Unterschiedliche Routen bleiben getrennt. Das sind passive Beobachtungsgruppen, keine kryptografisch bestätigten Anfrage-/Antwortpaare. Fehlende Sender-/Zielidentitäten werden nicht erfunden. Auch gleiche Tags/Auth-Codes/Routen im selben Zeitfenster können kollidieren; die vorhandene Regel reduziert das Risiko, beseitigt es nicht. [O02], [O03]

**Wichtiger Speicherunterschied:** Beacons `PacketHash()` enthält bei TRACE Payload-Typ, Pfadlänge und Payload, aber nicht die konkreten SNR-Pfadbytes. Unterschiedliche Fortschrittslängen ergeben verschiedene Paket-Hashes. Bei identischer Länge/Payload bleiben hingegen SNR-Varianten unter demselben Hash. `packet_observations` hat `UNIQUE(packet_hash, observer_id)` und `ON CONFLICT DO NOTHING`. Mehrere Observer bleiben getrennt, weitere Empfänge desselben Zustands beim selben Observer nicht. [B09], [B10], [B16]

`packets.parsed_payload` wird beim Konflikt nicht aktualisiert. Die gespeicherten Beobachtungen besitzen zwar eigene `path_bytes`, aber die TRACE-Tagansicht baut ihren SNR-Verlauf aus der Paket-Payloadrepräsentation; die allgemeine Detailantwort ersetzt bei TRACE die ausgegebenen Beobachtungs-`pathBytes` durch die angefragten Hashes. **S:** Eine lückenlose individuelle TRACE-SNR-Chronik folgt daraus nicht; die zuerst gespeicherten SNR-Werte eines Paket-Hashes können spätere Varianten verdecken. OnAirs Empfangsarchiv erhält diese Varianten, soweit sie tatsächlich angekommen und nicht vor Archivierung verloren gegangen sind. [B10], [B17], [O01]

Zusätzlich heißt das Listenfeld `best_payload` zwar sinngemäß „vollständigste Beobachtung“, seine SQL-Auswahl vergleicht aber die Länge von `pathHashes`, nicht von `snrValues`. Bei derselben angefragten Route mit anwachsender SNR-Liste wird die spätere vollständigere Messung deshalb nicht allein wegen zusätzlicher SNR-Werte bevorzugt. Das ist ein unmittelbar aus SQL ableitbarer Unterschied zwischen Beschreibung und Verhalten, kein ausgeführter Produktionsfehlernachweis. [B10], [B15]

### 3.2 TRACE: SNR, Hin-/Rückweg und Kartendarstellung

| Frage | Befund |
|---|---|
| Welcher Hop hat den SNR gemessen? | Beide ordnen `snr[i]` dem empfangenden `route[i]` zu. Für `i>0` beschreibt er den Empfang von `route[i-1]`. Der Vorgänger des ersten Hops ist ohne weitere Evidenz unbekannt. |
| Werden neue vollständige Routen rekonstruiert? | Beacon löst die bereits angefragte Hashfolge auf; es erfindet keine fehlenden Hop-Identitäten. Seine Aufnahme in `known_routes` verlangt eindeutige Kandidaten, aber keine vollständige SNR-Abdeckung. Eine gespeicherte angefragte Route ist deshalb nicht automatisch vollständig erfolgreich durchlaufen. |
| Hin-/Rückweg | Beide behalten wiederkehrende Hop-Einträge in der Datenfolge. Eine allgemeine sichere Erkennung der Wendestation oder der ursprünglichen Endgeräte ist nicht belegt. OnAirs Einzelkarte hält wiederholte gerichtete Durchläufe und zeigt deren SNR getrennt; Min/Max einer Messgruppe sind ausdrücklich keine Hin-/Rückwegwerte. |
| Fehlender/mehrdeutiger Hop | Beacon liefert `none`/`ambiguous` samt Kandidaten; OnAir markiert Mehrdeutigkeit und unterdrückt dort historische Kartenpositionen. Beide vermeiden Linien über unbekannte Zwischenhops in den untersuchten Kartenfunktionen. |
| Beacon-Karte | Im Paketpfad wird genau eine TRACE-Route gezeigt. `pathPoints` dedupliziert wiederkehrende Node-IDs; damit bildet die Kartenlinie die Hin-/Rückwegsequenz nicht vollständig ab. Es gibt hier keine Prüfung der SNR-Vollständigkeit vor Zeichnung einer sonst aufgelösten Strecke. |
| OnAir-Karte | Zwei einzelne Empfänge vergleichbar; Zeit-/Hopfilter, historische Positionen, Richtungspfeile und SNR-Beschriftungen. Linien verlangen benachbarte lokalisierte Hops mit SNR. Quelle bleibt unbekannt, Ziel ungesichert. |
| Historie | Beacon: Cursor-Tagliste und Tagdetail innerhalb der Retention. OnAir: Chronik bis 5.000 gelesene TRACE-Empfänge, 100 Gruppen/Verläufe und 200 Punkte je Verlauf; zusätzliche paginierte Einzelkarte. |
| Verschiedene Routen zwischen Stationen | Beacon besitzt Endpunktsuche im allgemeinen `known_routes`-Katalog. OnAir trennt TRACE-Verläufe nach Route und erlaubt Kartenvergleich. Eine dedizierte, identitätsgesicherte TRACE-Routenwechselchronik für dasselbe Sender-/Empfängerpaar ist in keinem der beiden Wege belegt. Erste/letzte Routen-Hashes sind nicht automatisch die Endgeräte. |

Quellen: [B07], [B15], [B18], [B19], [O01–O05].

**Tatsächlich übertragbarer Beacon-Vorteil:** Aus eindeutig aufgelösten, bereits mit SNR belegten TRACE-Nachbarpaaren erzeugt Beacon zusätzliche Kanten. OnAir nutzt solche Messungen bisher in TRACE-Auswertungen, aber nicht als weitere Evidenzklasse seiner Nachbaranalyse. Der erste Hop wird dabei zu Recht nicht mit einer erfundenen Quelle verknüpft. [B07], [O06]

### 3.3 DISCOVER

**I – beide:** DISCOVER_REQ und DISCOVER_RESP werden dekodiert. Antwortdaten enthalten Tag, Rolle, SNR der Suchanfrage beim antwortenden Gerät und entweder acht Public-Key-Präfixbytes oder einen vollständigen 32-Byte-Key. Dieser SNR ist **nicht** der RX-SNR des mitgehörten Antwortpakets beim Observer. Beide Decoder unterscheiden diese Bedeutung; OnAirs Discovery-Zeilen verwenden allerdings die kürzere Beschriftung „SNR“. [B07], [B20], [O02], [O07]

**I – OnAir:** Eigener Arbeitsablauf mit Gruppierung nach Tag, Scope und 60-s-Fenster; abweichende Anfragen werden getrennt. Antworten ohne mitgehörte Anfrage bleiben sichtbar. Vollkeys bzw. Präfixe bleiben im Archiv; ein Präfix wird nur bei genau einem bekannten Treffer zum Vollkey erweitert. Mehrdeutige Präfixe werden nicht einem Kandidaten zugeschlagen. Antworten derselben Identität mehrerer Observer werden innerhalb der Gruppe zusammengefasst, mit Empfangszähler und SNR-Min/Max. Die Observerliste gilt für die ganze Gruppe; die Antwortaggregation enthält keine vollständige Zuordnung jedes SNR-Samples zu seinem Observer. Der Suchende bleibt unbekannt. [O07]

**I – Beacon:** Typisierte Payload im Paketinspektor, einschließlich `requestSnr`, `pubKey`, `pubKeyPrefixOnly`; Speicherung in `packets.parsed_payload`. Im untersuchten Router, Schema und Webfeature ist kein entsprechender Discovery-Sessiondienst bzw. eigener Discovery-Tab vorhanden. Taggleichheit wird hier nicht zu einer eigenen Messreihe gruppiert. Historische Antworten können über das Paketarchiv betrachtet werden, sind aber keine Discovery-Sitzungschronik. [B07], [B09–B11], [B20], [B23]

**I – zusätzliche Topologieauswertung:** Beacon erzeugt bei einer Antwort mit vollständigem 32-Byte-Key eine Nachbarkante, wenn sowohl der Observer als auch der Responder bereits als Node existieren. Gespeichert wird **der RX-SNR des Observers**, nicht `requestSnr`. Ein acht Byte langes Präfix wird hierfür nicht expandiert. Eine nicht mitgehörte Anfrage verhindert diesen Vorgang nicht: Der Beleg betrifft den Empfang `Responder → Observer`, nicht den unbekannten Suchenden. Der Code erzeugt aus dem Payload-SNR keine identifizierte Strecke `Suchender → Responder`. [B07]

**Grenzen:** Die Kante speichert einen aktuellen SNR und einen Zähler, keine eigene DISCOVER-SNR-Zeitreihe. TRACE-/DISCOVER-Kantenupdates erfolgen im untersuchten Ingest-Ablauf bereits vor dem Ergebnis der Beobachtungs-Deduplizierung. Brokerkopien können daher den Nachbarzähler erhöhen, obwohl die Beobachtung nur einmal persistiert. Der bloße Kantenzähler ist kein Zähler unabhängiger Funkmessungen. [B07], [B10]

**Weitere Eingangsvoraussetzung:** `handlePacket` liest das Envelope-Feld `direction`, verwendet es aber im untersuchten Paketpfad nicht als RX-Filter. Die Deutung als Empfangsevidenz setzt daher passende Observer-/Brokerdaten voraus; bei ebenfalls gelieferten TX-Meldungen schützt dieser Codepfad die Nachbarableitung nicht durch eine explizite Richtungsprüfung. OnAirs TRACE-, Discovery- und Flood-Nachbarfunktionen verlangen hingegen `direction == 'rx'`. Das reale Brokerverhalten wurde nicht überprüft. [B07], [O03], [O06], [O07]

## 4. Hash-Kollisionen und Identitätsauflösung

### 4.1 Das konkrete `dd4c42`-Beispiel

Die Namen und Präfixe stammen aus dem Auftrag, nicht aus einer unabhängig verifizierten Abfrage des lokalen Meshes. Für die Bit-/Präfixbetrachtung genügt die angegebene Zeichenfolge:

| Gerät/Kandidat | 1 Byte | 2 Byte | 3 Byte | 4 Byte |
|---|---|---|---|---|
| Funkfeuer Bridge 02: `dd4c42a1…` | `dd` | `dd4c` | `dd4c42` | `dd4c42a1` |
| Funkfeuer Ampleben: `dd4c42d1…` | `dd` | `dd4c` | `dd4c42` | `dd4c42d1` |
| Früherer Kandidat: `dd4c42b1…` | `dd` | `dd4c` | `dd4c42` | `dd4c42b1` |

**S, sicher aus den angegebenen Präfixen:** Alle drei kollidieren auch bei **drei Byte**. Eine Umstellung gewöhnlicher Pfade auf drei Byte würde gerade diesen Fall nicht lösen. Vier Byte unterscheiden diese drei angegebenen Kandidaten, sind aber weiterhin keine vollständige Identität. Gewöhnliche Pfade und TRACE verwenden unterschiedliche Breitenkodierung: reguläre Pfade 1/2/3 Byte; TRACE-Payloadflags liefern über `1 << (flags & 3)` andere Breiten. Die Beacon-Dokumentation nennt für TRACE 1/2/4 Byte; OnAirs Decoder berechnet auch den Wert 8, während Beacons untersuchter Datenbankresolver nur 1–4 Byte unterstützt. Daraus wird hier keine allgemeine Firmware-Zusage für 8-Byte-TRACE abgeleitet. [B16], [B21], [O02], [O09]

### 4.2 Was Beacon tatsächlich macht

- **Vollidentitäten getrennt:** `nodes.public_key` ist UNIQUE; `node_short_ids` ist nach `(node_id, iata)` organisiert, nicht nach einem angeblich eindeutigen Kurzpräfix. Präfixindizes 1–4 Byte ermöglichen mehrere Kandidaten. Die drei Geräte werden auf dieser Ebene nicht zusammengelegt. [B09]
- **Kontext ja, Wahrscheinlichkeit nein:** `ResolvePathHashes` verzweigt nach Präfixbreite; SQL filtert IATA und Node-Rolle 2/3. Ein Treffer ergibt `high`, mehrere `ambiguous`, keiner `none`. Es gibt dort keinen Nachbarschaftsscore, keine Bayes-Wahrscheinlichkeit, kein Distanzranking und keinen globalen Pfadoptimierer. [B21], [B22]
- **Bewusste Produktentscheidung:** Die Design-FAQ lehnt das Raten ausdrücklich ab und bevorzugt sichtbare Kandidaten. Das stimmt grundsätzlich mit dem Resolver überein. [B24]
- **Statistiken/Pfade:** `known_routes` wird nur für komplett eindeutig aufgelöste Hashfolgen geschrieben. Periodisches `ReconfirmRoutes` verwirft gespeicherte Routen bei neu auftretender Mehrdeutigkeit, unter Berücksichtigung der ursprünglichen Präfixbreite. Unaufgelöste Pakete bleiben dennoch im Archiv. Diese Selektion begünstigt eindeutig bekannte Netzausschnitte; Routenzahlen sind keine vollständige Netzabdeckung. [B07], [B10]

**Wichtige Einschränkung des Labels `high`:** Es bedeutet „ein bekannter Kandidat im gewählten IATA und Rollenfilter“, nicht „Identität durch Funkmessung bewiesen“. Unbekannte Geräte oder Kandidaten außerhalb dieses Ausschnitts können fehlen. Eine regionale Filterung darf bei Fernempfang nicht als geografischer Identitätsbeweis ausgegeben werden.

**Konkrete Inkonsistenz beim TRACE-Merge:** `resolveTraceRoute` bewertet pro IATA und behält pro Hop den höchsten Rang (`high > ambiguous > none`). Meldet Gebiet A einen Kandidaten, Gebiet B einen anderen einzelnen Kandidaten, ersetzt der zweite gleichrangige Treffer den ersten nicht und es entsteht keine Kandidatenunion. Ebenso kann ein einzelner Treffer die Mehrdeutigkeit eines anderen Gebiets überstimmen. **S:** Die vereinigte Route kann eindeutiger aussehen, als es die gesamte Beobachtungslage rechtfertigt. Dieses Verfahren nicht übernehmen. [B15]

**Konkrete Grenze der Nachbarbereinigung:** `ReconfirmNeighbors` prüft Abwesenheit bzw. Kollision von `prefix_4`, während ein alter Eintrag aus einem früher noch eindeutigen 1-/2-/3-Byte-Paar stammen kann. Die Tabelle enthält keine ursprüngliche Präfixbreite und keinen Evidenztyp. Neue `dd4c42a1`-/`dd4c42d1`-Kandidaten haben verschiedene vier Byte; eine nachträglich entstandene Drei-Byte-Mehrdeutigkeit wird durch diese Bereinigung allein nicht erkannt. Vollkey-Geräte verschmelzen nicht, aber alte Kanten können eine überholte Zuordnung behalten. [B09], [B10]

### 4.3 Vergleich mit OnAir

OnAirs `resolve_path_tokens` berücksichtigt bekannte Geräte einschließlich anderer Rollen und längere tatsächlich beobachtete Tokens. Bei Mehrdeutigkeit bleibt der Rohhash erhalten. Die Aggregation geschieht vor Identitätsauflösung; neue Kollisionen lassen sich daher bei späterer Auswertung berücksichtigen. Karten-/Distanzberechnung und Routenplanung schließen mehrdeutige Identitäten aus. Das ist für diesen Auftrag die passendere Grundregel. [O06], [O08], [O10]

Es bestehen dennoch Grenzen: TRACE und Discovery haben eigene, einfachere Resolver gegen `names`; sie verwenden nicht automatisch dieselbe Kandidatenbasis wie die Nachbaranalyse. Eine vollständige Kandidatenliste mit Begründung fehlt dort. Historische Positionen sind zeitbezogen, die dafür verwendete Namens-/Identitätsauflösung basiert aber auf dem heutigen bekannten Bestand. Ein bisher unbekannter oder nicht mehr berücksichtigter Kandidat lässt sich durch keinen dieser Resolver ausschließen. [O03–O08]

**Empfehlung:** Kandidaten und Evidenz sichtbar machen, Rohpräfix und Breite erhalten und „im bekannten Bestand eindeutig“ von einer durch Vollkey belegten Identität unterscheiden. Nachbarschaft und geografische Nähe dürfen allenfalls als beschriftete Hinweise dienen, nicht als automatische Zusammenführung. Für das konkrete Beispiel bleibt `dd`, `dd4c` und `dd4c42` mehrdeutig, solange mehrere Kandidaten in Betracht kommen.

## 5. Datenbank- und Performance-Strategien

### 5.1 Nachbar-, Zeit- und Fernverbindungsanalyse

Beacon gewinnt Kanten aus mehreren Quellen: ADVERT-Absender zum ersten Forwarder, direkt empfangene ADVERTs zum Observer, aufeinanderfolgende gemessene TRACE-Hops, volle DISCOVER_RESP-Identitäten zum Observer sowie explizite MQTT-`/neighbors`-Reports. Fehlende Node-Einträge führen zum Auslassen einer Kante; ein fehlender Eintrag im nächsten Neighbor-Report löscht die frühere Kante nicht. Das Feld `heard_secs_ago` wird im Report eingelesen, aber im gezeigten Schreibpfad nicht als Messzeit benutzt. [B07], [B08], [B25]

`node_neighbors` speichert pro geordnetem Paar/IATA einen kumulierten `observation_count`, `first_seen`, `last_seen`, einen letzten nichtleeren SNR und Scope. Das ersetzt keine Stichprobenhistorie. Updates nutzen `NOW()`, nicht durchgehend den ursprünglichen Funkempfangszeitpunkt. Besonders wichtig: ADVERT-Kanten werden als `(Sender, Forwarder)`, TRACE-/Observer-Kanten als `(Empfänger, Sender)` geschrieben. Die SQL-Quelle weist selbst darauf hin; die Cross-IATA-Suche betrachtet deshalb beide Orientierungen. **S:** Ein generischer Pfeil aus der Spaltenreihenfolge wäre fachlich falsch; der gemeinsame Zähler mischt zudem unterschiedliche Evidenzarten. [B10], [B19]

Beacons Cross-IATA-Suche kombiniert gespeicherte Quell- und Zielsegmente mit einer Nachbarkante über die Gebietsgrenze. Suchbreite und Ergebnismenge sind begrenzt. Das ist eine **zusammengesetzte Verbindungsmöglichkeit**, kein Beweis, dass ein bestimmtes Paket die gesamte Kette durchlaufen hat oder alle Abschnitte gleichzeitig nutzbar waren. Die Suche verwendet keine zeitgleichen historischen Gerätepositionen. [B19]

OnAir speichert Roh-Flood-Pfade und Paaraggregate einschließlich Vorwärts-/Rückwärtszählern. Das Basis-Nachbarergebnis zählt Empfangsevidenz und verwendet aktuelle Positionen für seine Entfernung. Die gesonderte Fernanalyse geht weiter: eingegrenzte Rohpakete, deduplizierte Inhaltsidentitäten, Empfangszähler, Richtung, Tage/Stunden, Beispielpakete und Positionen aus gültigen, bis dahin bekannten ADVERTs. Spätere Positionen werden nicht rückwirkend eingesetzt; fehlende Positionen und mehrdeutige Kandidaten werden gezählt. Sie ist auf 31 Tage und 25.000 passende Empfänge begrenzt. [O06], [O08]

**S:** Für belastbare historische Fernstrecken ist OnAir bereits differenzierter. Beacons Stärken liegen in zusätzlichen Evidenzquellen und überregionaler Organisation. Ein lange beobachteter Nachbar ist weder automatisch aktuell erreichbar noch bidirektional; häufige Beobachtung ist ohne Dedup-Regel keine Anzahl unabhängiger Messungen.

### 5.2 Skalierungsmechanismen und Übertragbarkeit

| Mechanismus | Tatsächlicher Beacon-Befund | OnAir / sinnvolle Konsequenz |
|---|---|---|
| Passende Indizes | B-Tree für Observer-/IATA-/Zeitabfragen, Präfixindizes je Breite, Keyset-Indizes, GIN für `known_routes.node_ids`, partieller Index auf Pfadbelege | OnAir hat Typ/ID-, Observer/ID-, Hash/ID- und partiellen Flood-Pfad/Zeit-Index. Erst konkrete langsame Abfrage und Plan prüfen. |
| Voraggregation | Stunden-Rollups u. a. für Traffic, Signalverteilungen, Pfade, Observer und Scopes | OnAir aggregiert Rohpfade und Nachbarpaare schon beim Schreiben. Zusätzliche Stundenreihen nur für tatsächlich teure wiederkehrende Abfragen. |
| Rollup-Korrektheit | Geschlossene Stunden, Lock pro Rollup-Durchlauf, begrenzte Nachholarbeit, Dirty-Hours nach Backfill; Rohdaten-Retention berücksichtigt Nachholrückstand mit Obergrenze | Bei späteren OnAir-Rollups Zeitgrenzen und verspätete Daten von Anfang an definieren; kein Bedarf, sofort diesen ganzen Scheduler zu bauen. |
| Caching | Redis mit TTL, Invalidierung, `singleflight` gegen gleichzeitige Cache-Misses, DB-Fallback | OnAir: Nachbarn 30 s, bis 64 Antwortvarianten mit ETag, Fernanalyse 120 s und zwei LRU-Einträge. Lokale Caches reichen oft. |
| Pagination | TRACE-Liste stabil nach Millisekundenzeit + Tag; Routenbelege nach Zeit + ID | OnAir nutzt ID-Cursor im Archiv und TRACE-Kartenbrowser. Session-Chroniken bleiben auf 5.000 Empfänge begrenzt und könnten gezielt verbessert werden. |
| Serverseitige Filter | Region/Observer/Typ/Zeitraum; WS-Filter vor Versand | OnAir filtert Archiv/Nachbarseiten serverseitig, WS liefert gemeinsamen Live-Datenstrom. WS-Filter erst bei vielen Clients oder messbar hohem Datenvolumen. |
| Streaming | Vorserialisierte Hub-Ereignisse, begrenzte Clientpuffer, Verlustmeldung; Frontend virtualisiert Paketlisten | OnAir hat begrenzte WS-Queues und ersetzt Überlauf durch Snapshot. Keine ungebremste Live-Liste nötig. |
| Archivbelege | Route-Evidence-Query nutzt Pfad-Digest **und volle Bytegleichheit**, Zeitfenster, Cursor und Limit; schließt TRACE aus | OnAir hat bereits gezielte Flood-Pfadabfragen. Eine sichtbare Verknüpfung vorhandener Evidenz bringt mehr als neue Infrastruktur. |
| Große Altbestände | Rollup-Nachholen mit Budgets, Retention und gestreamter Backup-Export; getrennte historische/aktuelle Abfrageanteile | OnAir: begrenzte Analyse und Cache, aber historische Positionsrekonstruktion liest ADVERTs vor dem Endzeitpunkt. Das kann mit Archivgröße wachsen und wäre separat zu messen. |
| Queue/Writer | Parallelität mit begrenztem Bytebudget; Lastspitzen können Daten verlieren | OnAir: Queue bis 10.000, ein Writer, maximal 100 Einträge pro Batch, regulär 5-s-Intervall. Queuefüllstand/Dropzahl wären sinnvolle Lastindikatoren. |

Quellen: [B03], [B06], [B09–B14], [B26], [B27], [O01], [O04], [O08], [O09].

**Kein Freibrief für beliebig große Abfragen:** Beacons TRACE-Detail liest alle Pakete eines Tags ohne eigene Pagination. OnAirs TRACE-Kartenbrowser begrenzt jeden Scan auf 500 Einträge und jede Seite auf 50 Treffer, filtert den Zeitraum jedoch erst nach dem ID-Scan. Sehr alte oder seltene Treffer können deshalb viele Seiten erfordern. Das sind konkrete Optimierungsansätze, keine Gründe für einen Stackwechsel. Auch Beacons nachträgliche Kanalentschlüsselung lädt über `ListUndecryptedGroupTextPackets` zunächst eine Ergebnisliste und verarbeitet sie danach; nicht jeder Archivpfad ist gebatcht oder gestreamt. [B10], [B30], [O04]

**Lastprofil und Ressourcen:** Mangels Messungen ist keine seriöse Zahl für Pakete/s oder RAM-Vorteil ableitbar. Ein regionales OnAir mit wenigen Observern und Clients profitiert vor allem von gezielten Indizes, Batches und lokalen Caches. Viele Gebiete, Broker und gleichzeitige analytische Abfragen rechtfertigen eher Voraggregation und stärkere Isolation. Für eine spätere Entscheidung wären Ankunftsrate/Spitzen, Writer-Lag, Queue-Drops, Archivwachstum, Zahl gleichzeitiger Clients und p95-Latenzen der konkreten Ansichten zu messen. PostgreSQL/Redis bringen zusätzliche Dienste, Backups, Konfiguration und Wartung mit. Python/SQLite bleiben daher der Ausgangspunkt.

## 6. UI-/UX-Bewertung

### Auffindbarkeit nach Benutzeraufgabe

| Benutzerfrage | Beacon-Arbeitsablauf | OnAir-Beurteilung und Konsequenz |
|---|---|---|
| „Was passiert gerade?“ | Packets mit Filtern, Live-Verbindungshinweis, virtualisierter Liste, aufklappbarer Analyse und Kartenpfad | OnAir bietet Live/Rohdaten/MeshLive bereits. Beacons Funktionsumfang ist kein Grund, diese Ansichten zusammenzuwerfen. |
| „Was gehört zu diesem TRACE?“ | Traces → Tagdetail → Paketinspektor → Beobachtung oder Hop-Kandidat → Gerät | Gut verknüpft. OnAirs Chronik hat Messwerte, aber kaum direkte Aktionen auf die zugrunde liegenden Empfänge/Geräte. |
| „Warum gilt diese Route als bekannt?“ | Route → RouteDetailPanel → gefilterte Beobachtungsbelege → Paket/Observer | Gutes Vorbild: Belege direkt vom Ergebnis erreichen. Bei TRACE stammt dieser allgemeine Evidence-Endpunkt allerdings nicht aus TRACE-Pfadbytes. |
| „Wer hat auf die Suche geantwortet?“ | Einzelpaketinspektor; keine eigene Discovery-Sitzungsansicht gefunden | OnAir bereits zielgerichteter, einschließlich „Suchanfrage nicht mitgehört“. |
| „Welche Verbindung ist schwach?“ | Hop-SNR bzw. Node-Nachbarn; Analytics-Signalansichten | OnAir hat schwächsten TRACE-Hop, Routenzeitverlauf und gerichtete SNR-Kartenlabels. Das sollte unmittelbar sichtbar bleiben. |
| „Welche Geräte kommen für diesen Hash infrage?“ | Farblich markierter Hop mit Kandidaten-Popover und Node-Aktionen | Kandidatenliste sinnvoll; Bedeutung von `high` präziser formulieren als Beacon. |
| „Wie sah die Strecke damals aus?“ | Archiv/Tag/Paket; Resolver nutzt aktuelle Node-Positionen | OnAirs historische TRACE-/Fernansicht fachlich geeigneter. |

Quellen: [B18], [B20], [B23], [B26], [B28], [O03–O08], [O11].

### Konzepte, die sinnvoll sind

**I:** Beacons Desktopansicht kombiniert Listen mit Detailpanels. `App.tsx` hält Untersuchungsfenster über bestimmte Tabwechsel hinweg, unterstützt URL-Parameter für Tab/Region/Paket/Beobachtung und baut weitere Detailansichten aus dem aktuellen Kontext auf. Gemeinsame `Section`-Blöcke in `DetailPanel` sind sichtbare Abschnitte, keine standardmäßig zugeklappten Accordions. Region und Verbindungszustand bleiben präsent. Kartenpfade lassen Unsicherheitslücken offen. [B18], [B23], [B28]

**S:** Für OnAir lohnt sich vor allem der kurze Weg **Messung → einzelner Empfang → Gerät/Funkstrecke → zurück zur unveränderten Messung**. Dafür reichen kleine Navigationshilfen und stabile Parameter; React, MapLibre und das Panel-System müssen nicht übernommen werden.

### Konzepte, die wir nicht unverändert übernehmen sollten

- **Entitätsnavigation als Hauptmodell:** Beacon hat Packets, Nodes, Observers, Routes, Traces, Channels, Analytics, Map. Das ist konsistent, verlangt aber Vorwissen darüber, in welcher Datenkategorie die Antwort liegt. Auch OnAirs derzeit 14 Tabs sind nicht durchgehend aufgabenorientiert. Beacons Tabzahl ist kein Zielwert; besser benannte Einstiege und Querverweise für konkrete Fragen.
- **Analyse hinter „Mehr“ auf Mobilgeräten:** Beacons untere Leiste priorisiert Packets, Channels, Map, Nodes; Observer, Routes, Traces und Analytics liegen im Overflow. Für einen Nutzer, der Funkstrecken messen will, ist gerade der relevante Einstieg weniger sichtbar. [B28]
- **Vollständiger Kontextverlust beim mobilen Tabwechsel:** Beacon schließt dort Panels und entfernt Teile der Auswahl; Desktop-Kontext wird besser bewahrt, aber auch Wechsel zu Map/Analytics räumen Panels ab. Dieses Verhalten ist implementiert, also kein pauschales Versprechen perfekter Kontextkontinuität. [B23]
- **Viele kleine Fachwerte und verschachtelte Fenster:** Schriftgrößen von teils 11–13 px und Kandidaten-/Analyse-Popovers erhöhen Dichte, aber auch Bedienaufwand. Lesbarkeit und Touch-Ziele müssen praktisch geprüft werden; der Code allein belegt keine gute Smartphone-Bedienbarkeit.
- **Routenlinien als Erfolgsbeweis:** Eine aufgelöste angefragte TRACE-Route ohne vollständige SNR-Werte darf nicht wie eine bestätigte durchlaufene Strecke wirken. Ebenso brauchen zusammengesetzte Cross-IATA-Routen eine andere Kennzeichnung als ein tatsächlich beobachteter Gesamtpfad.

**Eigener OnAir-Handlungsbedarf:** `static/trace.js` und `static/discovery.js` rendern Messgruppen derzeit als `<details>`; relevante Route, Observer und Einzelwerte liegen hinter dem Aufklappen. Auch die Fernanalyse ist in `index.html` in einem `<details>`-Bereich. Das widerspricht den vorgegebenen Designprinzipien bereits heute. Kurze offene Ergebniszeilen mit sichtbaren Kernaussagen und optionalem Detailwechsel sind die naheliegende Verbesserung. [O11]

## 7. Funktionen, die OnAir bereits besser oder gleichwertig abdeckt

1. **Konservativer Umgang mit Kollisionen:** Rohpräfixe bleiben in Nachbaraggregaten erhalten, neue Mehrdeutigkeiten werden bei der Auflösung berücksichtigt; keine geografisch erratene Geräteidentität. Beacon bietet dagegen bessere Kandidatenpräsentation, aber keinen überlegenen probabilistischen Resolver. [O06], [B21–B24]
2. **TRACE-Messgruppen und Routenzeitreihen:** Zeitfenster/Auth-Code/Route trennen Gruppen; SNR-Min/Max und 200-Punkte-Verläufe sind bereits implementiert. Beacon hat in dem untersuchten TRACE-Feature keinen gleichartigen Hop-Zeitreihenvergleich. [O03], [B15], [B18]
3. **Einzelempfang und gerichteter TRACE-Kartenvergleich:** OnAir bewahrt Rohereignisse und wiederkehrende Hops, zeigt bis zu zwei Empfänge mit historischen Positionen und getrennten Durchlauf-SNR. Beacon dedupliziert mehr und vereinfacht die Kartenfolge. [O01], [O04], [O05], [B16–B18]
4. **Discovery-Sitzungen mit unvollständiger Beobachtung:** Verwaiste Antworten, unbekannter Suchender, Vollkey/Präfix und Mehrfachempfänge sind explizit behandelt. [O07]
5. **Historische Fernverbindungsbelege:** Empfangszeitbezogene Positionen, getrennte Paket-/Empfangs-/Richtungszahlen und fehlende Evidenz sind bereits vorhanden. [O08]
6. **Schlanke Performance-Grundlagen:** WAL, Batch-Writer, Paarvoraggregation, Cursor, begrenzte historische Arbeit, Caches und ETags sind schon da. „Beacon hat Caching/Pagination, OnAir nicht“ wäre falsch. [O01], [O04], [O06]
7. **Alternative Kandidatenrouten:** Die vorhandene BFS-/Yen-Suche erlaubt mehrere kürzeste schleifenfreie Wege und eine Option nur für beobachtete Richtung. Das ist eine andere, bereits nützliche Fähigkeit als Beacons gespeicherter Routenbestand. [O10]

## 8. Funktionen, die OnAir tatsächlich fehlen

### Im Vergleich zu implementierten Beacon-Funktionen

- **Nachbarevidenz aus TRACE und DISCOVER_RESP sowie strukturierten `/neighbors`-Reports.** OnAirs Nachbarpipeline beschränkt sich auf Flood-Hopfolgen. Der zusätzliche Nutzen hängt von verfügbaren Daten und eindeutig identifizierten Enden ab. [B07], [B25], [O06]
- **Durchgängige Kandidatenlisten mit Geräteverknüpfung** in TRACE-/Discovery-Ergebnissen; OnAir markiert dort Mehrdeutigkeit, liefert aber nicht die vollständige Erklärung und Navigation. [B18], [O03], [O07]
- **Durchgängiger Messung-/Paket-/Gerät-Detailfluss und teilbarer UI-Zustand.** Teilverknüpfungen sind vorhanden, aber kein Beacon-ähnlicher allgemeiner Untersuchungsfluss. [B23], [O11]
- **Eigener paginierter Katalog vollständig beobachteter/aufgelöster Pfade mit direkten Belegen**, getrennt von der Graphplanung. OnAir speichert bereits Rohpfade; deren Existenz ist nicht die fehlende Funktion, sondern die entsprechende nutzerseitige Katalog-/Belegansicht. [B19], [B26], [O06], [O10]
- **Explizite IATA-/Mehrbrokerorganisation und Cross-IATA-Suche**, falls OnAir künftig ein entsprechend überregionales Produkt werden soll. Das ist eine strategische Erweiterung, kein akutes Defizit für ein regionales Mesh.
- **Persistente Stunden-Rollups für umfangreiche Langzeitstatistiken.** OnAir hat Pfad-/Paaraggregate, aber nicht Beacons breites Analytics-Rollupmodell. Bedarf zuerst messen. [B09], [B14], [O01]

### Nicht als Beacon-Vorsprung ausgeben

Ein probabilistischer Hashresolver, eine identitätsgesicherte DISCOVER-Suchender→Responder-Historie, sichere automatische TRACE-Hin-/Rückwegsegmentierung und eine vollständige zeitbezogene Node-Topologie sind in den untersuchten Beacon-Datenwegen **nicht** nachgewiesen. Ein expliziter Vergleich von TRACE-Routenwechseln zwischen denselben zweifelsfrei identifizierten Endgeräten wäre auch für Beacon zusätzliche Arbeit. Es fehlt also kein bereits belegter „magischer“ Kollisionsmechanismus, den OnAir nur übernehmen müsste.

## 9. Konkrete Verbesserungsideen

Prioritäten bedeuten Diskussionsreihenfolge, keine Implementierungsfreigabe. Aufwand ist relativ: **klein** = begrenzte UI-/Antworterweiterung, **mittel** = mehrere Datenwege/Tests, **groß** = dauerhaftes zusätzliches Modell und Betriebslogik. Keine Zeitschätzung ohne Detailentwurf.

| Idee | Nutzen | Aufwand | Risiken / notwendige Begrenzung | Priorität |
|---|---|---|---|---|
| **1. Kandidaten sichtbar machen und Resolverbegriffe vereinheitlichen**: Rohhash, Bytebreite, alle bekannten Vollkeys, Belegart und Mehrdeutigkeitsgrund | Sehr hoch für `dd4c42`; verhindert Scheingenauigkeit und erklärt Ausschlüsse | Mittel; bestehende Resolver abstimmen, zunächst lesende API-/UI-Erweiterung | Kandidatenbasis/Alter offenlegen; keine automatische Wahl nach Entfernung; Vollkey und Präfixtreffer unterscheiden | **P1** |
| **2. Offene Messungszeilen und direkte Belegnavigation**: TRACE/Discovery ohne verpflichtendes Accordion; Aktionen auf Einzelpakete, Geräte und Karte, mit Rückweg | Hoher täglicher UX-Nutzen; nutzt vorhandene Daten | Klein bis mittel | Zeitfenster, Filter und Scrollposition erhalten; mobile Detailansicht nicht zur Sackgasse machen | **P1** |
| **3. TRACE-Kanten als eigene Evidenzansicht**, zunächst aus vorhandenen Rohdaten berechnet | Ergänzt Flood-Nachbarn um gerichtete SNR-Messungen | Mittel | Nur benachbarte eindeutige Hops mit tatsächlichem SNR; ersten Vorgänger nicht erfinden; Rohereignis/Observer/Zeit referenzieren; Wiederholungen separat zählen | **P1** |
| **4. DISCOVER-Antwortempfang als eigene Observer-Strecke** anzeigen: Responder→Observer mit RX-SNR; Payload-SNR getrennt | Zusätzliche direkte Messung ohne bekannte Anfrage | Mittel | Observer-ID muss belastbar auf Node-Vollkey abgebildet sein; Vollkey nicht automatisch aus einem Präfix ersetzen; `requestSnr` gehört zum unbekannten Suchenden→Responder | **P2** |
| **5. Historische TRACE-/Discovery-Suche gezielt erweitern**: Zeitraum/Pagination, eindeutige Limitanzeige, Gruppen nicht still an Seitengrenzen schneiden | Alte Messungen erreichbar, weniger wiederholtes Dekodieren | Mittel; zunächst vorhandene Indizes/Abfragen untersuchen | Zeit-/ID-Cursor korrekt kombinieren, Gruppen über Seitengrenzen erhalten; Index/Migration wäre separat zu entscheiden | **P2** |
| **6. Beobachtete Pfade neben geplanten Kandidaten anbieten**, mit Varianten und einzelnen Belegen | Trennt tatsächliche Pfadbeobachtung von Graphkombination; erleichtert Routenvergleich | Mittel | TRACE-Sollroute nicht als erfolgreich traversiert zählen; unsichere Endpunkte nicht als Stationen festlegen; historische Identitätsänderungen beachten | **P2** |
| **7. Evidenzsemantik vor einer dauerhaften Kantenvereinheitlichung definieren**: Sender, Empfänger, Quelle, Zeit, Paket-/Empfangszahl | Verhindert Beacons gemischte Richtungs- und Zählerprobleme | Mittel, Bestandteil von Ideen 3/4 | Keine Umdeutung vorhandener Flood-Zähler; keine irreversible Auflösung von Rohhashes | **P1 als Voraussetzung für 3/4** |
| **8. Messbare Engpässe statt Stackumbau bearbeiten**: Writer-Lag/Drops und langsame Endpunkte erfassen, dann genau einen Index/Cache/Rollup optimieren | Hoher Nutzen, wenn Lastproblem real ist | Klein für Bestandsaufnahme, mittel für gezielte Optimierung | Messung darf Ingestion nicht belasten; Rollups brauchen Dirty-/Retention-Regeln | **P2, lastabhängig** |
| **9. Explizite Regionen-/Mehrbrokerfunktionen nur bei realem Ausbau** | Nutzen für verteiltes Netz, regional eher gering | Groß | Region ist Filterkontext, kein Identitätsbeweis; globale WS-Koordination nicht nebenbei einführen | **P3** |

### Sinnvolle Abgrenzung für die Diskussion

Zuerst Ideen 1 und 2 diskutieren: Sie verbessern Nachvollziehbarkeit und Bedienung ohne neue Infrastruktur. Danach Idee 3 als begrenzte, lesende Analysefunktion mit klaren Evidenzregeln; Idee 4 benötigt zusätzlich belastbare Observer-Identitäten. Ein gemeinsames persistentes Funkstreckenmodell, neue Rollups oder eine Datenbankmigration sind **keine** Voraussetzung für diese ersten Schritte.

Eine spätere Prüfung sollte insbesondere folgende Fälle abdecken: drei kollidierende `dd4c42`-Identitäten; neue Kollision nach einer früheren Auflösung; dasselbe Tag in mehreren Scopes/Zeitfenstern; TRACE mit fehlendem SNR und wiederholten Hops; unterschiedliche SNR-Varianten bei gleicher Payload/Pfadlänge; DISCOVER ohne Anfrage; doppelte Observer-/Brokerempfänge; verschobene oder fehlende historische Position. Das sind Abnahmekriterien für mögliche Folgearbeit, keine in diesem Auftrag neu implementierten Tests.

### Die fünf interessantesten Erkenntnisse für MeshCore OnAir

1. **Beacon löst das `dd4c42`-Problem nicht durch Wahrscheinlichkeit oder Nachbarwissen.** Alle drei Beispielkandidaten kollidieren auch bei drei Byte; regionale Eindeutigkeit ist kein gesicherter Identitätsnachweis.
2. **OnAir ist bei passiven TRACE-/DISCOVER-Messreihen bereits stark.** Zeit-/Auth-/Routengruppierung, Einzelempfänge, historische Positionen und gerichtete TRACE-SNR-Karten sind keine aufzuholenden Beacon-Funktionen.
3. **Der fachlich interessanteste Zugewinn sind zusätzliche Funkstreckenbelege.** TRACE kann gerichtete Hop-SNR liefern; DISCOVER_RESP den Empfang Responder→Observer mit dessen RX-SNR. Herkunft und Richtung müssen getrennt bleiben.
4. **Beacons beste UX-Idee ist die direkte Verbindung von Ergebnis und Beleg.** Für OnAir sind offene Ergebniszeilen, Kandidatenlisten und kurze Wege zu Paket/Gerät/Karte wertvoller als ein neues Frontendframework.
5. **Skalierung bedeutet hier vor allem begrenzte und passende Arbeit.** OnAir besitzt viele Grundlagen bereits. Weitere Indizes, Pagination oder kleine Rollups sollten einem gemessenen Problem folgen; der Vergleich begründet keinen Wechsel von SQLite/Python.

## Quellenverzeichnis und konkrete Fundstellen

Die Angaben nennen Dateien und Einstiegspunkte; GitHub-Links sind auf den untersuchten Commit fixiert. Lokale OnAir-Links sind relativ zu diesem Dokument. Zusammengefasste Referenzbereiche wie `[B05–B08]` bezeichnen die jeweiligen Einträge, nicht zusätzliche Quellen.

- **[B01]** beacon-server: [go.mod:1](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/go.mod#L1); [README.md:32](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/README.md#L32).
- **[B02]** beacon-web: [package.json:19](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/package.json#L19).
- **[B03]** beacon-docs: [docker-deployment-type1/docker-compose.yml:1](https://github.com/MeshCore-Beacon/beacon-docs/blob/9de500cfa5be98f4d8affe68aae68d2631750d73/docker-deployment-type1/docker-compose.yml#L1).
- **[B04]** beacon-flutter-app: [README.md:40](https://github.com/MeshCore-Beacon/beacon-flutter-app/blob/15e6f514ce188a74bf7d792da9024a307a275153/README.md#L40); [pubspec.yaml:11](https://github.com/MeshCore-Beacon/beacon-flutter-app/blob/15e6f514ce188a74bf7d792da9024a307a275153/pubspec.yaml#L11).
- **[B05]** beacon-server: [cmd/beacon/main.go:352](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/cmd/beacon/main.go#L352); [internal/ingest/ingest.go:252](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/ingest/ingest.go#L252).
- **[B06]** beacon-server: [internal/ingest/queue.go:26](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/ingest/queue.go#L26); [internal/ingest/queue.go:59](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/ingest/queue.go#L59).
- **[B07]** beacon-server: [internal/ingest/packet.go:548](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/ingest/packet.go#L548); [internal/ingest/packet.go:653](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/ingest/packet.go#L653); [internal/ingest/packet.go:786](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/ingest/packet.go#L786).
- **[B08]** beacon-server: [internal/ingest/side_effects.go:85](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/ingest/side_effects.go#L85).
- **[B09]** beacon-server: [db/migrations/001_baseline.sql:15](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/migrations/001_baseline.sql#L15); [db/migrations/001_baseline.sql:292](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/migrations/001_baseline.sql#L292); [db/migrations/001_baseline.sql:438](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/migrations/001_baseline.sql#L438); [db/migrations/002_known_routes_node_ids_gin.sql:5](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/migrations/002_known_routes_node_ids_gin.sql#L5).
- **[B10]** beacon-server: [db/queries/queries.sql:386](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/queries/queries.sql#L386); [db/queries/queries.sql:802](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/queries/queries.sql#L802); [db/queries/queries.sql:1587](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/queries/queries.sql#L1587); [db/queries/queries.sql:1745](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/queries/queries.sql#L1745); [db/queries/queries.sql:1797](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/queries/queries.sql#L1797).
- **[B11]** beacon-server: [internal/api/router/router.go:107](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/api/router/router.go#L107).
- **[B12]** beacon-server: [internal/hub/hub.go:65](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/hub/hub.go#L65); [internal/ws/handler.go:31](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/ws/handler.go#L31).
- **[B13]** beacon-server: [internal/cache/cache.go:106](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/cache/cache.go#L106); [internal/cache/reader.go:4](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/cache/reader.go#L4).
- **[B14]** beacon-server: [internal/background/rollup.go:98](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/background/rollup.go#L98); [internal/background/tasks.go:102](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/background/tasks.go#L102); [db/queries/rollup.sql:1](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/queries/rollup.sql#L1).
- **[B15]** beacon-server: [db/traces.go:93](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/traces.go#L93); [db/traces.go:136](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/traces.go#L136); [internal/api/handlers/traces.go:47](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/api/handlers/traces.go#L47).
- **[B16]** meshcore-go: [packet.go:278](https://github.com/meshcore-go/meshcore-go/blob/427ab2cc863ebd7aa2f502d93c09c7268059ec01/packet.go#L278); [trace.go:73](https://github.com/meshcore-go/meshcore-go/blob/427ab2cc863ebd7aa2f502d93c09c7268059ec01/trace.go#L73).
- **[B17]** beacon-server: [db/packets.go:490](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/packets.go#L490).
- **[B18]** beacon-web: [src/features/traces/TraceDetailPanel.tsx:15](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/src/features/traces/TraceDetailPanel.tsx#L15); [src/features/map/packet-path.ts:36](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/src/features/map/packet-path.ts#L36); [src/features/map/packet-flow.ts:11](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/src/features/map/packet-flow.ts#L11).
- **[B19]** beacon-server: [db/routes.go:79](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/routes.go#L79); [db/routes.go:163](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/routes.go#L163).
- **[B20]** beacon-web: [src/features/packets/payload-renderers.tsx:470](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/src/features/packets/payload-renderers.tsx#L470); [src/features/packets/payload-renderers.tsx:515](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/src/features/packets/payload-renderers.tsx#L515).
- **[B21]** beacon-server: [db/store.go:39](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/store.go#L39); [db/queries/queries.sql:1636](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/queries/queries.sql#L1636); [db/queries/queries.sql:1680](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/queries/queries.sql#L1680).
- **[B22]** beacon-server: [internal/api/packets.go:272](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/api/packets.go#L272).
- **[B23]** beacon-web: [src/App.tsx:153](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/src/App.tsx#L153); [src/App.tsx:214](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/src/App.tsx#L214); [src/App.tsx:279](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/src/App.tsx#L279).
- **[B24]** beacon-docs: [docs/high-level-design.md:1040](https://github.com/MeshCore-Beacon/beacon-docs/blob/9de500cfa5be98f4d8affe68aae68d2631750d73/docs/high-level-design.md#L1040); [docs/high-level-design.md:1044](https://github.com/MeshCore-Beacon/beacon-docs/blob/9de500cfa5be98f4d8affe68aae68d2631750d73/docs/high-level-design.md#L1044).
- **[B25]** beacon-server: [internal/ingest/neighbors.go:33](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/ingest/neighbors.go#L33).
- **[B26]** beacon-server: [db/route_evidence.go:34](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/route_evidence.go#L34); [db/queries/route_evidence.sql:5](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/queries/route_evidence.sql#L5).
- **[B27]** beacon-server: [internal/backup/export.go:5](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/backup/export.go#L5); [db/queries/series.sql:1](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/db/queries/series.sql#L1).
- **[B28]** beacon-web: [src/components/BottomNav.tsx:8](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/src/components/BottomNav.tsx#L8); [src/components/DetailPanel.tsx:7](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/src/components/DetailPanel.tsx#L7); [src/features/routes/RouteDetailPanel.tsx:1](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/src/features/routes/RouteDetailPanel.tsx#L1); [src/features/packets/PacketVirtualList.tsx:1](https://github.com/MeshCore-Beacon/beacon-web/blob/bd5b8951e4a30976e84efd8348c14597a962e50e/src/features/packets/PacketVirtualList.tsx#L1).
- **[O01]** OnAir: [onair_archive.py](../onair_archive.py) (Zeile 29, `class Archive`); [onair_archive.py](../onair_archive.py) (Zeile 196, `def traces`); [onair_archive.py](../onair_archive.py) (Zeile 506, `def _run`); [onair_archive.py](../onair_archive.py) (Zeile 408, `def neighbor_response`).
- **[O02]** OnAir: [onair_payload.py](../onair_payload.py) (Zeile 23, `if kind == 9:`); [onair_payload.py](../onair_payload.py) (Zeile 84, `if kind == 11:`).
- **[O03]** OnAir: [onair_trace.py](../onair_trace.py) (Zeile 9, `def trace_sessions`).
- **[O04]** OnAir: [onair_trace_map.py](../onair_trace_map.py) (Zeile 11, `def browse`); [onair_trace_map.py](../onair_trace_map.py) (Zeile 39, `def detail`).
- **[O05]** OnAir: [static/trace-map.js](../static/trace-map.js) (Zeile 3, `function traceMapSnrSegments`); [static/trace-map.js](../static/trace-map.js) (Zeile 35, `function draw()`).
- **[O06]** OnAir: [onair_neighbors.py](../onair_neighbors.py) (Zeile 36, `def add_path_pairs`); [onair_neighbors.py](../onair_neighbors.py) (Zeile 100, `def resolve_path_tokens`); [onair_neighbors.py](../onair_neighbors.py) (Zeile 125, `def neighbor_summary`).
- **[O07]** OnAir: [onair_discovery.py](../onair_discovery.py) (Zeile 9, `def discovery_sessions`).
- **[O08]** OnAir: [onair_distance.py](../onair_distance.py) (Zeile 44, `class Positions`); [onair_distance.py](../onair_distance.py) (Zeile 108, `def analyze`); [onair_distance.py](../onair_distance.py) (Zeile 218, `def response`).
- **[O09]** OnAir: [requirements.txt](../requirements.txt) (Zeile 1, `paho`); [onair_mqtt.py](../onair_mqtt.py) (Zeile 223, `hash_size =`); [onair_web.py](../onair_web.py) (Zeile 345, `@app.websocket`).
- **[O10]** OnAir: [onair_routes.py](../onair_routes.py) (Zeile 6, `def route_graph`); [onair_routes.py](../onair_routes.py) (Zeile 74, `def shortest_routes`).
- **[O11]** OnAir: [static/index.html](../static/index.html) (Zeile 8, `<button id="tab-live"`); [static/trace.js](../static/trace.js) (Zeile 10, `function renderTraces`); [static/discovery.js](../static/discovery.js) (Zeile 4, `function renderDiscovery`); [static/app.js](../static/app.js) (Zeile 464, `let archiveQuery`); [static/distance.js](../static/distance.js) (Zeile 1).

- **[B29]** beacon-docs: [docs/high-level-design.md:145](https://github.com/MeshCore-Beacon/beacon-docs/blob/9de500cfa5be98f4d8affe68aae68d2631750d73/docs/high-level-design.md#L145), regionale Auflösung und anschließende UI-Regeln.
- **[B30]** beacon-server: [internal/ingest/backfill.go:103](https://github.com/MeshCore-Beacon/beacon-server/blob/202acc6cc8f616819a3577c57a7009ea1a48c0dd/internal/ingest/backfill.go#L103), `BackfillChannelMessages` und Listenverarbeitung.
