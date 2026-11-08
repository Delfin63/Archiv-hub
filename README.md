# Archiv Hub

Automatisches Beschriften und Einsortieren von Dokumenten.

Die Pipeline nimmt PDF oder Bild entgegen, erkennt den Text (OCRmyPDF/Tesseract,
deu+eng), klassifiziert ihn per LLM (DeepSeek, OpenAI-kompatibel) und legt das
durchsuchbare PDF unter `/ablage/<speicherort>/<ziel-pfad>/` ab. Ein Speicherort
ist ein benannter Host-Ordner, der als Docker-Volume eingebunden wird. Die Ziele
(mit Speicherort, Pfad, Beschreibung, optionalem Hub und Jahresordner) werden in
`data/ziele.json` gepflegt. Unsichere oder unvollständige Zuordnungen landen in
`data/zur-pruefung/`.

Port: **8002** (Host). Start ausschliesslich über Docker Compose.

## Auf dem Mac: bauen, starten, testen

```bash
cd "/Volumes/OWC 8TB/Programmieren/entwicklung/projects/archiv-hub"

# 1) .env anlegen und Werte eintragen
cp .env.example .env

# 2) Passwort-Hash erzeugen (Ausgabe in .env unter ARCHIV_HUB_PASSWORD_HASH eintragen)
.venv/bin/python generate-password-hash.py

# 3) Image bauen und Container starten (Port 8002)
docker compose up -d --build
```

In `.env` mindestens setzen:

- `ARCHIV_HUB_SECRET_KEY` (z. B. `openssl rand -hex 32`)
- `ARCHIV_HUB_PASSWORD_HASH` (aus Schritt 2, **nicht** das Klartext-Passwort)
- `ARCHIV_HUB_ABLAGE_BASIS=./data/ablage` (Standard-Testordner, siehe unten)
- `DEEPSEEK_API_KEY` (für die Klassifizierung)

## Speicherorte

Ein Speicherort ist ein benannter Host-Ordner, der im Container unter
`/ablage/<name>` eingebunden wird. Ein Container sieht nur eingebundene Ordner –
deshalb bestimmt der Nutzer die Ordner selbst (z. B. OWC, Benutzerordner,
Synology).

- **standard** ist fest eingebaut. Sein Host-Pfad ist `ARCHIV_HUB_ABLAGE_BASIS`
  und wird im Container unter `/ablage/standard` eingebunden. Standard:
  `./data/ablage` (nur ein lokaler Testordner – nie echte Daten hineinlegen).
- **Weitere Speicherorte** werden mit
  `66-archiv-hub-speicherort-hinzufuegen.command` angelegt. Das Skript schreibt
  `compose.speicherorte.yaml` (Volumes) und `data/speicherorte.json`
  (Name, Host-Pfad, Label) und startet den Container neu.
  `67-archiv-hub-speicherort-entfernen.command` entfernt nur die Einbindung,
  nie Dateien oder Ordner.

Beide Dateien (`compose.speicherorte.yaml`, `data/speicherorte.json`) sind
maschinenspezifisch und werden nicht eingecheckt.

**Ablage auf der Synology:** Die Synology hat eigene Speicherorte. In der `.env`
der Synology setzen:

```
ARCHIV_HUB_ABLAGE_BASIS=/volume1/archiv
```

Den Standard-Ordner vor dem ersten Start auf der Synology anlegen
(`mkdir -p /volume1/archiv`). Weitere Speicherorte auf der Synology werden über
eine eigene `compose.speicherorte.yaml` und `data/speicherorte.json` direkt auf
der NAS angelegt (siehe `docs/README.md`). `deploy-synology.sh` überträgt diese
beiden Dateien bewusst nicht.

## Ziele verwalten (Oberfläche)

Nach dem Login im Browser:

- `http://localhost:8002/einstellungen/ziele` – Ziele anlegen, bearbeiten,
  löschen, aktiv/inaktiv schalten. Jedes Ziel hat einen Speicherort und einen
  Pfad innerhalb dieses Speicherorts, der über einen Ordner-Navigator gewählt
  wird (statt den Pfad zu tippen). Die Seite listet die Speicherorte samt
  Host-Pfad.

Solange kein aktives Ziel existiert, landen alle Dokumente in
`data/zur-pruefung/` (mit deutlichem Hinweis in der Oberfläche).

## Mit dem DeepSeek-Key testen

```bash
# Anmelden (Session-Cookie speichern)
curl -c cookies.txt -X POST \
  -d 'password=<DEIN_PASSWORT>' \
  http://localhost:8002/login

# Dokument hochladen (PDF oder Bild)
curl -b cookies.txt \
  -F 'file=@/pfad/zum/dokument.pdf' \
  http://localhost:8002/api/upload
```

Die Antwort enthält `status` (`abgelegt` oder `zur_pruefung`) und das Ziel.
Jeder Vorgang wird als eine JSON-Zeile in `data/archiv.log` protokolliert.

## API

- `POST /login` – Passwort (Formularfeld `password`), setzt Session-Cookie
- `POST /logout`
- `POST /api/upload` – Multipart-Feld `file` (PDF oder Bild)
- `GET/POST /api/ziele` – Ziele lesen/anlegen (Feld `speicherort`)
- `PUT/DELETE /api/ziele/<id>` – Ziel ändern/löschen (löscht nie Dateien)
- `GET /api/speicherorte` – Speicherorte (Name, Host-Pfad, Label) lesen
- `GET /api/ablage/ordner?speicherort=…&pfad=…` – Unterordner einer Ebene lesen
  (max. 500 Einträge, Feld `mehr` bei mehr)
- `POST /api/ablage/ordner` – Ordner anlegen (JSON: `speicherort`, `pfad`, `name`)

Alle Endpunkte ausser `/login`, `/logout` und `/health` sind passwortgeschützt.

## Konfiguration

- `data/ziele.json` – die Ablage-Ziele (Laufzeitdaten, nicht deployed)
- `data/speicherorte.json` – zusätzliche Speicherorte (Name, Host-Pfad, Label;
  maschinenspezifisch, nicht eingecheckt)
- `compose.speicherorte.yaml` – Docker-Volumes der Speicherorte
  (maschinenspezifisch, nicht eingecheckt)
- `app/config/hubs.yaml` – optionale Gruppierung der Hubs (Name + Beschreibung)
- `app/config/settings.yaml` – LLM-Anbieter/-Modell, Sicherheitsschwelle,
  Eingangsordner
- `.env` – Secrets (`ARCHIV_HUB_*`, `DEEPSEEK_API_KEY`), nie einchecken

## Test

```bash
.venv/bin/python -m pytest test_pipeline.py -q
```

Weitere Hinweise: `docs/README.md`.
