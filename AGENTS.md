# Archiv Hub – Hinweise für Agenten

Dieses Dokument führt die gemeinsamen Regeln der bestehenden Hubs
(translation-hub, guitar-hub, healing-hub) zusammen. Übersetzungs- und
Projektspezifisches der einzelnen Hubs wird bewusst nicht übernommen.

## Prioritätenkette

Bei Widersprüchen gilt (übernommen aus AI_RULES.md §1):
1. ausdrücklicher aktueller Auftrag des Nutzers
2. AI_RULES.md
3. DEVELOPMENT_RULES.md
4. RELEASE_CHECKLIST.md

Bei Unsicherheit: stoppen und nachfragen.

## Verbindliche Arbeitsregeln

- Nur den ausdrücklich beauftragten Teil ändern. Keine eigenmächtigen
  Verbesserungen, Refactorings, Layout-, Architektur- oder Strukturänderungen.
- Bestehende Ordner- und Dateistrukturen respektieren. Bestehende
  Namenskonventionen exakt fortführen. Keine neuen Projektpfade erfinden.
- Kleine, nachvollziehbare Schritte statt grosser Umbauten. Vor grösseren
  Umbauten (Datenmodell, Docker-Struktur, Refactoring) zuerst einen Commit
  erstellen.

## Git-Regeln

- **Commits nur auf ausdrückliche Anweisung des Nutzers.** Das weicht bewusst
  von AI_RULES.md §4 („jede freigegebene Teilaufgabe unmittelbar committen“)
  ab und gilt für diesen Hub.
- Vor jeder Änderung `git status` und den aktuellen Branch prüfen.
- Vor jedem Release muss der Working Tree sauber sein.
- Keine pauschalen Rücksetzungen ohne Auftrag (`git reset --hard`,
  `git restore .`, `git checkout .`, force push).
- Bestehende Tags und Releases niemals verändern, verschieben oder überschreiben.
- Releases nur nach `RELEASE_CHECKLIST`-Prinzipien: Commit, Tag, Release-Ordner,
  Versionsnummer, sauberer Working Tree.

## Tests

- Nur gezielte Tests für die aktuelle Änderung durchführen.
- Keine Testdaten dauerhaft in Datenbank oder Projekt belassen.
- Temporäre Testdateien und Diagnosehilfen vollständig entfernen.
- Keine Testergebnisse behaupten, die nicht tatsächlich geprüft wurden.
- Wenn etwas nicht geprüft werden konnte, dies ausdrücklich sagen.

## Berichte

- Abschlussberichte müssen Fakten enthalten, keine Vermutungen.
- Immer angeben: geänderte Dateien, durchgeführte Tests, `git diff --stat`,
  `git status`.

## Laufzeit & Port

- **Start ausschliesslich über Docker Compose**, nie über `python app/app.py`
  oder `flask run`:
  `cd projects/archiv-hub && docker compose up -d --build`
- **Port: 8002** (Host). Der Container lauscht intern auf 8000.
- OCR läuft im Docker-Container (OCRmyPDF/Tesseract, deu+eng).

## Konfiguration & Secrets

- `app/config/hubs.yaml` und `app/config/settings.yaml` liegen im Repository.
- Die Ablage-Ziele liegen in `data/ziele.json` (Laufzeitdaten, nicht deployed).
  Die Ablage-Basis wird im Container als `/ablage` eingebunden (HOST-Pfad:
  `ARCHIV_HUB_ABLAGE_BASIS`).
- **`.env` liegt im Hub-Wurzelordner** (`projects/archiv-hub/.env`), wie im
  healing-hub. Vorlage: `.env.example`. Sie ist gitignored.
- API-Schlüssel liegen NUR in `.env` und werden nie in Code, Datenbank oder
  Logs gespeichert.
- Passwort-Login über `ARCHIV_HUB_PASSWORD_HASH` (Hash, kein Klartext),
  erzeugt mit `generate-password-hash.py`.

## Versionierung

- Versionsnummer in `app/version.txt` (Format `X.Y`).
- Versionen werden mit `release-version.sh` abgeschlossen (Git-Tag + Release-
  Ordner + neue Entwicklungsversion) – wie im healing-hub.
