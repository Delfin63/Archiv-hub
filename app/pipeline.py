"""Ablage-Logik: Prüfung, Dateiname, Konfliktvermeidung, Log.

Die Funktionen sind bewusst frei von Flask und Dateisystem-Nebenwirkungen, wo
möglich, damit sie direkt testbar sind.
"""

import json
import re
from datetime import datetime
from pathlib import Path

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# Pflichtfelder: eine Zuordnung braucht einen Ordner und einen Dokumenttyp.
# Das Datum ist NICHT Pflicht – Dokumente ohne Datum bekommen das Scandatum.
REQUIRED_FIELDS = ("dokumenttyp",)


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
    """True, wenn das Dokument nicht automatisch abgelegt werden darf.

    "ziel_id" wird hier nicht mehr geprüft: Der Aufrufer entscheidet, ob ein
    vorhandener Ordner gewählt wurde (ziel_id = id) oder ein neuer angelegt
    werden soll (ziel_id = "neu" mit dem Namen in "ordner").
    """
    if missing_required(result):
        return True
    # Ein Datum ist nur dann ein Fehler, wenn es vorhanden, aber ungültig ist.
    if str(result.get("datum") or "").strip() and not is_valid_date(result.get("datum")):
        return True
    if not is_valid_sicherheit(result):
        return True
    return float(result["sicherheit"]) < threshold


def output_filename(
    result,
    original_name=None,
    fallback_datum=None,
    ordner=None,
):
    """Baut "Datum – Ordnername – Dokumentname.pdf".

    Das Datum ist das DOKUMENTDATUM (Rechnungsdatum, Briefdatum). Fehlt es im
    Dokument, wird ``fallback_datum`` verwendet (üblicherweise das Scandatum).

    Leere Teile werden weggelassen – es entstehen keine Lücken und kein
    Platzhalter wie "Unbekannt".
    """
    result = result or {}
    datum = str(result.get("datum") or "").strip() or str(fallback_datum or "").strip()
    ordner = str(ordner or "").strip()
    name = str(result.get("dokumentname") or "").strip()
    typ = str(result.get("dokumenttyp") or "").strip()

    # Ohne inhaltlichen Namen hilft der Dokumenttyp als Rückfall.
    if not name:
        name = typ

    if not name and not ordner:
        # Nichts Brauchbares von der KI: Originalname behalten.
        if original_name:
            stamm = Path(str(original_name)).stem.strip()
            if stamm:
                if datum and not re.search(r"\d{4}-\d{2}-\d{2}", stamm):
                    return f"{datum} – {stamm}.pdf"
                return f"{stamm}.pdf"
        return f"{datum}.pdf" if datum else "Dokument.pdf"

    # Ordnername und Dokumentname nicht doppelt nennen: sind sie gleich,
    # wird der Name nur einmal aufgeführt.
    teile = []
    if datum:
        teile.append(datum)
    if _gleich(ordner, name):
        if name:
            teile.append(name)
    else:
        if ordner:
            teile.append(ordner)
        if name:
            teile.append(name)
    if not teile:
        teile.append(name or ordner or "Dokument")

    return " – ".join(teile) + ".pdf"


def _gleich(a, b):
    """Vergleicht zwei Namen ohne Rücksicht auf Gross-/Kleinschreibung und
    deutsche Umlaute (Uebungsanleitungen == Übungsanleitungen)."""
    def norm(x):
        x = str(x or "").strip().lower()
        for von, zu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"),
                        ("_", ""), ("-", ""), (" ", "")):
            x = x.replace(von, zu)
        return x

    return norm(a) == norm(b)


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


# Zeichen, die in Dateinamen nicht vorkommen dürfen (macOS/Windows/Synology).
_UNSAFE_NAME_CHARS = '<>:"/\\|?*\x00-\x1f'


def safe_filename(name, fallback="Dokument.pdf", endung=".pdf"):
    """Bereinigt einen vom Nutzer vorgegebenen Dateinamen.

    Entfernt Pfadtrenner und Steuerzeichen, kürzt auf 200 Zeichen und setzt
    die gewünschte ``endung`` (Standard .pdf). Ein leeres Ergebnis fällt auf
    ``fallback`` zurück.
    """
    name = str(name or "").strip()
    # Nur den reinen Dateinamen behalten (keine Pfadanteile).
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(f"[{_UNSAFE_NAME_CHARS}]", "", name)
    name = name.strip(" .")
    if not name:
        return fallback
    endung = str(endung or ".pdf")
    if not endung.startswith("."):
        endung = "." + endung
    if not name.lower().endswith(endung.lower()):
        # Vorhandene Endung ersetzen, sonst anhängen.
        name = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name) + endung
    return name[:200]


def safe_ordnername(name, fallback="Sonstiges"):
    """Bereinigt einen von der KI vorgeschlagenen Ordnernamen.

    Erlaubt sind Buchstaben, Ziffern, Leerzeichen, Punkt, Komma, Bindestrich
    und Unterstrich. Pfadtrenner und Sonderzeichen fliegen raus, damit der
    Name keinen Pfad bilden kann.
    """
    name = str(name or "").strip()
    name = name.replace("\\", "/").split("/")[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "", name)
    # Mehrfache Leerzeichen zusammenfassen, Ränder entfernen.
    name = re.sub(r"\s+", " ", name).strip(" .-")
    # Eine allfällige Dateiendung abschneiden.
    if name.lower().endswith(".pdf"):
        name = name[:-4].strip(" .-")
    if not name or name in (".", ".."):
        return fallback
    return name[:100]
