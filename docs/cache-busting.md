# Inhaltsbasierte Asset-Versionen

## Untersuchung

Der vorhandene Talli-Bahn-Checkout (`/home/oliver/src/talli-bahn`, Stand
`0ec8092`) bindet CSS und JavaScript ohne Versionsparameter ein.
`app/main.py` liefert die Startseite per `FileResponse`; `app/static/sw.js`
verwendet den manuell benannten Cache `talli-shell-v3` und versucht zuerst das
Netzwerk. Eine automatische Inhaltsversionierung war in diesem Checkout nicht
vorhanden. Die gewünschte Lösung wurde daher direkt für OnAir umgesetzt.

OnAir liefert `/` und `/static/` über FastAPI aus. Docker kopiert bereits
`onair_*.py` und `static/`; der neue Helfer wird dadurch ohne Build-/Compose-
Änderungen berücksichtigt. Eine produktive nginx-Konfiguration liegt im
Repository und in dieser Arbeitsumgebung nicht vor.

## Umsetzung

`onair_assets.py` versieht beim Ausliefern von HTML alle lokalen CSS-/JS-Links
unter `/static/` mit `?v=<12 Hexzeichen>`. Der Wert ist der SHA-256-Präfix des
Dateiinhalts. Jede Datei hat ihre eigene Kennung. Die Quelldateien bleiben
unversioniert und müssen nicht manuell gepflegt werden. Es gibt keinen
Buildschritt, keine zusätzliche Abhängigkeit und keinen mtime-basierten Hashcache.
Auch ein Austausch bei gleicher Dateigröße und gleichem Zeitstempel wird erkannt.

| Antwort | Cacheverhalten |
| --- | --- |
| `/` und `/static/index.html` | HTML mit aktuellen Asset-Links; `Cache-Control: no-cache` |
| Statische Datei mit passendem `v` | `public, max-age=31536000, immutable` |
| Unversionierte Datei oder nicht mehr passendes `v` | `no-cache`; Inhalt vor Wiederverwendung prüfen |
| Passendes `If-None-Match` | `304`, ohne erneute Übertragung des Dateiinhalts |

Statische Dateien erhalten als ETag den vollständigen SHA-256-Hash. Hash und
Antwort verwenden dieselben eingelesenen Bytes. Eine alte Versions-URL liefert
nach einer Änderung den aktuellen Inhalt mit `no-cache`, niemals den aktuellen
Inhalt mit einem neuen langfristigen Cacheeintrag unter einer falschen Kennung.
Es wird kein Archiv früherer Dateiversionen angelegt.

Die bestehende Pfad-/Methodenprüfung von `StaticFiles` bleibt erhalten; HEAD
liefert dieselben Header wie GET ohne Body. API- und WebSocket-Routen sowie deren
Cache-/Aktualisierungslogik werden nicht verändert. Bereits offene Seiten laden
Skripte nicht im Hintergrund neu: Neue Kennungen werden beim nächsten Laden der
HTML-Seite entdeckt.

## Abhängigkeiten und dynamische Ressourcen

Alle 14 lokalen CSS-/JS-Dateien einschließlich Theme, Leaflet, MeshLive-Effekten
und den Funktionsskripten sind direkt im HTML eingebunden und werden einzeln
versioniert. Skriptreihenfolge und `defer` bleiben unverändert. Es gibt derzeit
keine ES-Modul-Imports, dynamischen Skriptloader, Worker oder Service Worker.
`fetch()` ruft API-Endpunkte auf; Kartenkacheln kommen weiterhin von OpenStreetMap.

Leaflets unveränderte Vendor-Dateien referenzieren außerdem Bilder für seine
Standardmarker/Layerkontrolle und eine Debug-Sourcemap. Diese Dateien sind im
vorhandenen Vendor-Verzeichnis nicht enthalten; OnAir verwendet eigene
SVG-/Div-Marker und keine solche Layerkontrolle. Diese bestehenden Referenzen
wurden nicht umgeschrieben. Künftig vorhandene, unversioniert nachgeladene lokale
Ressourcen erhalten durch den gemeinsamen Static-Handler ebenfalls `no-cache`
und einen Inhalts-ETag; dieser Pfad ist mit einer Bild-Fixture getestet.

Falls später ES-Module mit eigenen Importketten eingeführt werden, müssen auch
deren Import-URLs versioniert werden. Ein HTML-Hash wird nicht automatisch an
relative Importe oder CSS-`url()`-Verweise vererbt. Aktuell ist dafür kein
Import-Rewriter erforderlich.

## nginx

HTML muss weiterhin von FastAPI kommen, damit die Kennungen erzeugt werden.
Ein direktes nginx-`try_files` auf die rohe `static/index.html` würde die Erzeugung
umgehen. Auch `/static/` sollte an den bestehenden FastAPI-Upstream weitergeleitet
werden, damit die hier implementierten Header und Inhalts-ETags gelten.

Query-Strings dürfen nicht entfernt werden. Ein vorgeschalteter Proxycache muss
sie in seinem Schlüssel berücksichtigen; nginx verwendet standardmäßig
`$scheme$proxy_host$request_uri`. Die Anwendung setzt die Cache-Header selbst;
sie dürfen nicht durch pauschale `expires`-/`Cache-Control`-Regeln oder
`proxy_ignore_headers Cache-Control` ausgehebelt werden. Bestehende WebSocket-
und Zugriffskonfiguration bleibt erhalten. Siehe die
[nginx-Dokumentation zum Proxycache](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_cache_key)
und zu
[proxy_ignore_headers](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_ignore_headers).

Es wurden keine Serverkonfigurationen geändert und kein Deployment durchgeführt.
Ein Ende-zu-Ende-Test durch den produktiven nginx war deshalb nicht Teil der Prüfung.

## Tests

- Gesamte Python-Suite: 116 Tests erfolgreich.
- Sechs neue Assettests: unveränderte Dateien (auch nach `touch`), geändertes CSS,
  JavaScript und ein Abhängigkeitsskript, identische Größe/mtime, unabhängige
  Versionen, starke/schwache ETags, 304, alte/falsche Versionen, unversionierte
  Bilder, beide HTML-Zugänge, HEAD, fehlende Dateien und schreibgeschützte Methoden.
- Der reale FastAPI-Handler liefert alle 14 lokalen CSS-/JS-Dateien unter den
  generierten URLs mit passendem MIME-Typ und korrektem Inhaltshash aus.
- Das vorhandene Offline-Browserharness verwendet jetzt das tatsächlich erzeugte
  HTML statt der rohen Quelldatei. Es prüft auch, dass alle 14 Styles/Skripte mit
  Versionsparametern geladen werden; API-/WebSocket-/Kachel-Fixtures bleiben lokal.
- Chromium-Regressionslauf erfolgreich: versionierte Ressourcen, MeshLive,
  Livefilter, Details, Pause/Resume und mobile Ansicht; Paketdarstellung und
  Tabreihenfolge stimmen mit `HEAD` überein.
- `git diff --check` ohne Befund.

```sh
PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v
python tests/browser_meshlive.py --compare-ref HEAD
```

Der Browsertest benötigt die vorhandenen Anwendungsabhängigkeiten und Playwright.
In dieser Arbeitsumgebung wurden ohne Installation die OnAir-Umgebung und das
bereits vorhandene Playwright kombiniert:

```sh
PYTHONPATH=/home/oliver/src/talli-air/.venv/lib/python3.13/site-packages \
  .venv/bin/python tests/browser_meshlive.py --compare-ref HEAD
```
