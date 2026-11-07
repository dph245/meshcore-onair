# WebSocket-Empfangsdeltas (P2b)

Vergleich mit P2a (`1cec060`) auf einem Intel Core i7-14700 mit Python 3.13.5
und Node 20.19.2. Synthetische Last mit 2.400 Updates im 250-ms-Raster,
entsprechend zehn Minuten bei 28 Empfängen pro Sekunde. Der Lauf hat keine
Wartezeit zwischen den Takten. Pro Update kommen sieben Empfänge von drei
abwechselnden Observern an, verteilt auf vier stark und zwei regelmäßig
belegte Gruppen sowie eine neue Gruppe. Der Startpuffer enthält 500 Gruppen.
Die Noise-Historie enthält im Hauptprofil 100 Messwerte je Observer.

Der Benchmark führt den tatsächlichen Dashboard-Pump und die Client-Queues
aus. Auf der Empfangsseite laufen der tatsächliche JavaScript-Message-Handler
und der Empfangscode des ausgeblendeten MeshLive-Tabs in getrennten
Node-Kontexten. Die Frontend-CPU enthält JSON-Parsing, Gruppen und Rohdaten,
aber kein DOM- oder Kartenrendering. Die Speicherwerte sind Spitzen-RSS je
Prozess, auf der Empfangsseite über alle simulierten Clients zusammen.
Die Datenmenge zählt UTF-8-JSON ohne WebSocket-/TLS-Overhead und Kompression.
Jede Clientzahl und Revision lief in einem eigenen Prozess.

## Reproduktion

```bash
for n in 1 10 30; do
  .venv/bin/python tools/benchmark_websocket.py --ref 1cec060 --clients "$n"
  .venv/bin/python tools/benchmark_websocket.py --clients "$n"
done
.venv/bin/python tools/benchmark_websocket.py --ref 1cec060 --clients 1 --ticks 240 --noise 500
.venv/bin/python tools/benchmark_websocket.py --clients 1 --ticks 240 --noise 500
```

## Hauptprofil

Pro regulärem Update sank das Mittel von **283.150 auf 72.534 Byte (−74,4 %)**,
das 95. Perzentil von 310.760 auf 72.542 Byte. Die Gesamtmenge enthält den
initialen Snapshot je Client und 2.400 Updates. Die Server-CPU misst den Pump
mit Fan-out über alle regulären Updates. Die Frontend-CPU enthält zusätzlich
den initialen Snapshot. Die Werte sind jeweils P2a → P2b.

| Clients | JSON gesamt (GB) | Server-CPU (s) | Davon JSON-Serialisierung (s) | Frontend-CPU gesamt (s) | Server-RSS (MiB) | Frontend-RSS gesamt (MiB) |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0,682 → 0,177 | 3,41 → 0,94 | 3,14 → 0,69 | 1,96 → 0,42 | 122,8 → 121,6 | 150,0 → 141,8 |
| 10 | 6,824 → 1,769 | 3,57 → 0,93 | 3,27 → 0,68 | 21,05 → 3,40 | 124,8 → 122,0 | 411,6 → 315,3 |
| 30 | 20,471 → 5,306 | 3,45 → 0,95 | 3,15 → 0,68 | 80,81 → 10,20 | 125,3 → 123,0 | 965,8 → 726,6 |

## Überlauf

Im Anschluss pausierte der letzte Client elf Takte. Im neunten Takt ersetzte
ein Snapshot die acht wartenden Frames. Beim Fortsetzen folgten zwei bereits
wartende Updates und danach ein reguläres Update. P2b prüfte zusätzlich die
lückenlose Folge ab der Snapshot-Sequenz. Alle anderen Clients erhielten jedes
Update unmittelbar. Nach der Wiederaufnahme stimmten Gruppen, Rohdaten und
Status bei jedem Client per SHA-256 mit dem Serverzustand überein. Der
Endzustand war auch zwischen P2a und P2b identisch.

| Clients | CPU am Überlauftakt, Server (ms) | CPU für den Snapshot, betroffener Client (ms) |
| ---: | ---: | ---: |
| 1 | 36,5 → 40,2 | 25,8 → 22,1 |
| 10 | 38,4 → 37,0 | 19,6 → 24,5 |
| 30 | 40,5 → 38,6 | 21,1 → 26,5 |

Der Überlauf-Snapshot hatte 6.752.511 → 6.752.522 Byte. Die maximale Summe
der JSON-Nutzdaten in der langsamen Queue lag bei 7.380.823 → 6.897.606 Byte.
Das ist die Summe der Framegrößen, während mehrere Queues im Prozess
dieselben serialisierten Frames referenzieren können. Der Aufwand eines
Vollsnapshots bleibt in derselben Größenordnung.

## Volle Noise-Historie

Im separaten Lauf mit einem Client, 240 Updates und 500 Noise-Messwerten je
Observer sank die mittlere Updategröße von 509.601 auf 326.920 Byte (−35,8 %).
Einschließlich des initialen Snapshots waren es 125,35 → 81,51 MB. Die
Server-CPU lag bei 0,51 → 0,32 s, die Frontend-CPU bei 0,28 → 0,15 s.
Der Anteil der unverändert übertragenen Noise-Historie erklärt die geringere
relative Einsparung.
