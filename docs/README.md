# Archiv Hub – Architektur

## Struktur

- `app/app.py` – Flask-Backend, Passwort-Login, `POST /api/upload`, UI + CRUD
- `app/classifier.py` – LLM-Klassifizierung (OpenAI-kompatibler Client)
- `app/ocr.py` – OCRmyPDF/Tesseract (deu+eng)
- `app/pipeline.py` – Ablage-Prüfung, Dateiname, Konflikte, Log
- `app/storage.py` – Ziele (`data/ziele.json`), Speicherorte, Pfadsicherheit unter `/ablage`
- `app/scanner.py` – Scan-Quellen (`data/scanner.json`)
- `app/config.py` – lädt `config/*.yaml` und `.env`
- `app/config/hubs.yaml` – optionale Gruppierung der Hubs (Name + Beschreibung)
- `app/config/settings.yaml` – LLM, Schwelle, Eingangsordner
- `data/ziele.json` – Ablage-Ziele (Laufzeitdaten, nicht deployed)
- `data/speicherorte.json` – zusätzliche Speicherorte (maschinenspezifisch, nicht eingecheckt)
- `compose.speicherorte.yaml` – Docker-Volumes der Speicherorte (maschinenspezifisch, nicht eingecheckt)
- `data/` – Laufzeitdaten (`zur-pruefung/`, `archiv.log`, `work/`, `input/`)

## Datenmodell

Ein Ziel in `data/ziele.json`:

- `id` – eindeutige Kennung
- `name` – Anzeigename
- `speicherort` – Name des Speicherorts (Standard: `standard`)
- `pfad` – Pfad innerhalb des Speicherorts (`/ablage/<speicherort>/<pfad>`)
- `beschreibung` – für die KI
- `hub` – optional, Name aus `hubs.yaml`
- `jahresordner` – true/false
- `aktiv` – true/false

Ein Speicherort in `data/speicherorte.json`:

- `name` – Kurzname (nur `a-z`, `0-9`, Bindestrich)
- `host_pfad` – Host-Ordner, der als `/ablage/<name>` eingebunden wird
- `label` – Anzeigename

Der Speicherort `standard` ist fest eingebaut und leitet sich aus
`ARCHIV_HUB_ABLAGE_BASIS` ab; er wird in `compose.yaml` eingebunden. Weitere
Speicherorte stehen in `data/speicherorte.json` und werden über
`compose.speicherorte.yaml` eingebunden.

## Datenfluss

```
POST /api/upload
      │  PDF/Bild
      ▼
OCR (app/ocr.py) ──► durchsuchbares PDF + Volltext
      │
      ▼
Klassifizierung (app/classifier.py) ──► JSON {ziel_id, datum, absender,
      │                                   dokumenttyp, sicherheit}
      ▼
Ablage (app/pipeline.py + app/storage.py)
      ├─ aktives Ziel + sicherheit >= Schwelle + gültige Angaben
      │     └─► /ablage/<speicherort>/<pfad>[/<jahr>]/YYYY-MM-DD – Absender – Dokumenttyp.pdf
      └─ sonst (unklar, unbekannte ziel_id, keine Ziele, unbekannter
            Speicherort) ──► data/zur-pruefung/
      │
      ▼
data/archiv.log (eine JSON-Zeile pro Dokument)
```

## Sicherheitsgrenzen

- Jeder Pfad wird per `realpath` geprüft und muss unter
  `/ablage/<speicherort>` liegen. Absolute Pfade, `..` und Symlinks, die aus
  der Einbindung hinausführen, werden abgelehnt. Der Speicherort-Name wird
  gegen `^[a-z0-9-]+$` geprüft, damit er keine Pfadtrenner enthält.
- Die App löscht nie Dateien oder Ordner. Bestehende Dateien werden nie
  überschrieben; Namenskonflikte werden mit `" (2)"` aufgelöst. Das Löschen
  eines Ziels löscht nie Dateien oder Ordner.
- Ein Ziel mit unbekanntem Speicherort landet in `data/zur-pruefung/`.
- API-Schlüssel liegen nur in `.env` (nie eingecheckt). Der Passwort-Login
  nutzt einen Passwort-Hash (`ARCHIV_HUB_PASSWORD_HASH`), keinen Klartext.
- Alle zustandsändernden Anfragen (`POST`, `PUT`, `PATCH`, `DELETE`) benötigen
  ein CSRF-Token der Sitzung. Es wird pro Sitzung erzeugt und als
  `X-CSRF-Token`-Header (oder Formularfeld `csrf_token`) erwartet; fehlt oder
  passt es nicht, antwortet die App mit `403`. `GET` bleibt frei. Die
  Skripte holen das Token über `archivCsrf()` aus `window.ARCHIV_HUB_CSRF`
  (`app/templates/base.html`, `app/static/archiv.js`).

## Speicherorte

`ARCHIV_HUB_ABLAGE_BASIS` ist der HOST-Pfad des Speicherorts `standard` und wird
im Container unter `/ablage/standard` eingebunden. Standard auf dem Mac:
`./data/ablage` (Testordner). Auf der Synology z. B. `/volume1/archiv`.

Weitere Speicherorte werden mit
`66-archiv-hub-speicherort-hinzufuegen.command` angelegt (macOS-Dialog), das
`compose.speicherorte.yaml` und `data/speicherorte.json` schreibt und den
Container neu startet. Auf der Synology legt man diese beiden Dateien direkt an,
da `deploy-synology.sh` sie nicht überträgt. Beispiel für
`compose.speicherorte.yaml` auf der Synology:

```yaml
services:
  archiv-hub:
    volumes:
      - "/volume1/archiv:/ablage/standard"
      - "/volume2/archiv-alt:/ablage/alt"
```

und passend dazu `data/speicherorte.json`:

```json
[
  {"name": "alt", "host_pfad": "/volume2/archiv-alt", "label": "Altes Archiv"}
]
```

`standard` muss in `data/speicherorte.json` nicht aufgeführt werden – die App
ergänzt ihn automatisch. Für die Anzeige nutzt sie bevorzugt den absoluten
Pfad `ARCHIV_HUB_ABLAGE_BASIS_ANZEIGE` (wird von Skript 60 bzw.
`deploy-synology.sh` aufgelöst) und fällt sonst auf
`ARCHIV_HUB_STANDARD_HOST_PFAD` zurück.
