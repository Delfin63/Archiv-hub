"""Ablage-Logik: Prüfung, Dateiname, Konfliktvermeidung, Log.

Die Funktionen sind bewusst frei von Flask und Dateisystem-Nebenwirkungen, wo
möglich, damit sie direkt testbar sind.
"""

import json
import re
from datetime import datetime
from pathlib import Path

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

REQUIRED_FIELDS = ("ziel_id", "datum", "absender", "dokumenttyp")


def is_valid_date(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def missing_required(result):
    """Liefert die Namen der fehlenden Pflichtfelder."""
    result = result or {}
    return [
        field
        for field in REQUIRED_FIELDS
        if not str(result.get(field) or "").strip()
    ]


def is_valid_sicherheit(result):
    value = result.get("sicherheit")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False
    return 0.0 <= value <= 1.0


def should_review(result, threshold):
    """True, wenn das Dokument nicht automatisch abgelegt werden darf."""
    if missing_required(result):
        return True
    if str(result.get("ziel_id") or "").strip() == "unklar":
        return True
    if not is_valid_date(result.get("datum")):
        return True
    if not is_valid_sicherheit(result):
        return True
    return float(result["sicherheit"]) < threshold


def output_filename(result):
    """Baut "YYYY-MM-DD – Absender – Dokumenttyp.pdf"."""
    datum = str(result["datum"]).strip()
    absender = str(result.get("absender") or "").strip()
    dokumenttyp = str(result.get("dokumenttyp") or "").strip()
    return f"{datum} – {absender} – {dokumenttyp}.pdf"


def unique_destination(directory, filename):
    """Liefert einen konfliktfreien Zielpfad. Bei Namenskonflikt wird " (2)"
    angehängt; bestehende Dateien werden nie überschrieben."""
    directory = Path(directory)
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem = Path(filename).stem
    suffix = Path(filename).suffix
    index = 2
    while True:
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def append_log(log_path, entry):
    """Hängt einen Datensatz als eine JSON-Zeile an data/archiv.log an."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
