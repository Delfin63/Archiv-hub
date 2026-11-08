"""Verwaltung der Ablage-Ziele, Speicherorte und der Pfadsicherheit.

Die Ziele (data/ziele.json) und Speicherorte (data/speicherorte.json) liegen
bewusst NICHT in app/config, sondern in data/, weil deploy-synology.sh nur den
Quellcode überträgt und data/ unangetastet lässt.
"""

import json
import re
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from . import config

SPEICHERORT_RE = re.compile(r"^[a-z0-9-]+$")

DEFAULT_SPEICHERORT = "standard"


# ---- Ziele ------------------------------------------------------------------

def ziele_path():
    return config.DATA_DIR / "ziele.json"


def _read_json_list(path):
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _write_json_list(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", "utf-8")
    tmp.replace(path)


def load_ziele():
    """Lädt Ziele und migriert fehlende Speicherort-Angaben auf "standard"."""
    ziele = _read_json_list(ziele_path())
    changed = False
    for ziel in ziele:
        if not ziel.get("speicherort"):
            ziel["speicherort"] = DEFAULT_SPEICHERORT
            changed = True
    if changed:
        save_ziele(ziele)
    return ziele


def save_ziele(ziele):
    _write_json_list(ziele_path(), ziele)


def new_id():
    return secrets.token_hex(6)


def find_target(ziele, ziel_id):
    for ziel in ziele:
        if ziel.get("id") == ziel_id:
            return ziel
    return None


def active_targets():
    return [ziel for ziel in load_ziele() if ziel.get("aktiv", True)]


def find_active_target(ziel_id):
    return find_target(active_targets(), ziel_id)


# ---- Speicherorte -----------------------------------------------------------

def speicherorte_path():
    return config.DATA_DIR / "speicherorte.json"


def load_speicherorte():
    """Nur die zusätzlichen Speicherorte (ohne den eingebauten "standard")."""
    return _read_json_list(speicherorte_path())


def save_speicherorte(speicherorte):
    _write_json_list(speicherorte_path(), speicherorte)


def locations():
    """Alle Speicherorte inklusive des eingebauten "standard"."""
    standard = {
        "name": DEFAULT_SPEICHERORT,
        "host_pfad": config.STANDARD_HOST_PFAD,
        "label": "Standard",
    }
    return [standard] + load_speicherorte()


def find_speicherort(name):
    for loc in locations():
        if loc.get("name") == name:
            return loc
    return None


def is_known_speicherort(name):
    return find_speicherort(name) is not None


# ---- Eingangskorb -----------------------------------------------------------
#
# Der Eingangskorb ist der Ordner, in den neue Dateien gelegt werden – per
# Upload oder indem ein Scanner direkt dorthin schreibt (macOS "Digitale
# Bilder" -> "Scannen in"). Die Dateien werden NICHT automatisch verarbeitet:
# der Nutzer sieht sie in der Oberfläche, prüft sie und stösst die Verarbeitung
# selbst an. Nach erfolgreicher Ablage wandert das Original nach
# data/input/erledigt/ (Variante C: nichts wird gelöscht).

ERLEDIGT_ORDNER = "erledigt"

# Endungen, die der Eingangskorb anzeigt und verarbeiten darf.
KORB_ENDUNGEN = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}


def korb_dir():
    """Eingangskorb (data/input)."""
    return config.INPUT_DIR


def korb_erledigt_dir():
    """Ablage der verarbeiteten Originale (data/input/erledigt)."""
    return korb_dir() / ERLEDIGT_ORDNER


def _korb_eintrag(path):
    """Beschreibt eine Datei im Korb für die Oberfläche."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return {
        "name": path.name,
        "endung": path.suffix.lower(),
        "groesse": stat.st_size,
        "geaendert": datetime.fromtimestamp(stat.st_mtime).isoformat(
            timespec="seconds"
        ),
    }


def list_korb():
    """Dateien im Eingangskorb, neueste zuerst. Unterordner werden ignoriert."""
    basis = korb_dir()
    if not basis.is_dir():
        return []

    eintraege = []
    for pfad in basis.iterdir():
        # Nur echte Dateien: "erledigt/" und alles andere fliegt raus.
        if pfad.is_symlink() or not pfad.is_file():
            continue
        if pfad.name.startswith("."):
            continue
        if pfad.suffix.lower() not in KORB_ENDUNGEN:
            continue
        eintrag = _korb_eintrag(pfad)
        if eintrag is not None:
            eintraege.append(eintrag)

    eintraege.sort(key=lambda e: e["geaendert"], reverse=True)
    return eintraege


def korb_datei(name):
    """Löst einen Korb-Dateinamen sicher auf (kein Pfad, keine Traversal)."""
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    if Path(name).name != name:
        return None
    pfad = korb_dir() / name
    # Nach resolve() prüfen, damit auch Symlinks nicht ausbrechen.
    try:
        if not pfad.resolve().parent == korb_dir().resolve():
            return None
    except OSError:
        return None
    return pfad if pfad.is_file() else None


def korb_erledigt(name):
    """Verschiebt ein verarbeitetes Original nach data/input/erledigt/.

    Variante C: das Original wird nie gelöscht. Existiert der Zielname schon,
    wird ein Zähler angehängt, damit nichts überschrieben wird.
    """
    quelle = korb_datei(name)
    if quelle is None:
        return None
    ziel_dir = korb_erledigt_dir()
    ziel_dir.mkdir(parents=True, exist_ok=True)

    ziel = ziel_dir / quelle.name
    zaehler = 2
    while ziel.exists():
        ziel = ziel_dir / f"{quelle.stem} ({zaehler}){quelle.suffix}"
        zaehler += 1

    shutil.move(str(quelle), str(ziel))
    return ziel


# ---- Pfadsicherheit ---------------------------------------------------------

def ablage_basis():
    return Path(config.ABLAGE_BASIS).resolve()


def speicherort_pfad(name):
    """Container-Pfad eines Speicherorts (/ablage/<name>)."""
    name = str(name or DEFAULT_SPEICHERORT).strip()
    if not SPEICHERORT_RE.match(name):
        raise ValueError("Ungültiger Speicherort-Name.")
    return (ablage_basis() / name).resolve()


def safe_ablage_path(speicherort, relative):
    """Löst ``relative`` unter /ablage/<speicherort> auf.

    Lehnt absolute Pfade, ``..`` sowie Symlinks ab, die aus der Einbindung
    hinausführen (realpath-Prüfung).
    """
    basis = speicherort_pfad(speicherort)
    value = str(relative or "").strip()
    if value in ("", "."):
        return basis

    p = Path(value)
    if p.is_absolute():
        raise ValueError("Pfad darf nicht absolut sein.")
    if ".." in p.parts:
        raise ValueError("'..' ist in Pfaden nicht erlaubt.")

    candidate = (basis / p).resolve()
    if candidate != basis and not candidate.is_relative_to(basis):
        raise ValueError("Pfad verlässt den Speicherort.")
    return candidate


def ziel_directory(ziel, datum=None):
    """Zielordner eines Ziels (unter /ablage/<speicherort>), optional mit Jahr."""
    speicherort = ziel.get("speicherort") or DEFAULT_SPEICHERORT
    rel = str(ziel.get("pfad") or "").strip()
    if ziel.get("jahresordner") and datum:
        year = str(datum)[:4]
        rel = str(Path(rel) / year) if rel else year
    return safe_ablage_path(speicherort, rel)


SYSTEM_FOLDERS = {
    "$RECYCLE.BIN",
    "@EADIR",
    "SYSTEM VOLUME INFORMATION",
    "LOST+FOUND",
}


def _validate_folder_name(name):
    name = str(name or "").strip()
    if not name:
        raise ValueError("Name fehlt.")
    if name in (".", "..") or name.startswith("."):
        raise ValueError("Name darf nicht mit einem Punkt beginnen.")
    if "/" in name or "\\" in name:
        raise ValueError("Name darf kein '/' oder '\\' enthalten.")
    if name.upper() in SYSTEM_FOLDERS:
        raise ValueError("Name ist nicht erlaubt.")
    return name


def list_folders(speicherort=DEFAULT_SPEICHERORT, pfad="", max_entries=500):
    """Listet die unmittelbaren Unterordner einer Ebene im Speicherort.

    Versteckte Ordner (Punkt am Anfang) und Systemordner werden übersprungen,
    Symlinks nicht verfolgt. Liefert ``(namen, mehr)``; ``mehr`` ist True, wenn
    mehr als ``max_entries`` Ordner existieren.
    """
    basis = safe_ablage_path(speicherort, pfad)
    names = []
    if basis.is_dir():
        for entry in sorted(basis.iterdir(), key=lambda e: e.name.lower()):
            try:
                if entry.is_symlink():
                    continue
                if not entry.is_dir():
                    continue
            except OSError:
                continue
            name = entry.name
            if name.startswith(".") or name.upper() in SYSTEM_FOLDERS:
                continue
            names.append(name)
    truncated = len(names) > max_entries
    return names[:max_entries], truncated


def create_folder(speicherort, pfad, name):
    """Legt einen Unterordner ``name`` unter /ablage/<speicherort>/<pfad> an."""
    name = _validate_folder_name(name)
    value = str(pfad or "").strip()
    relative = str(Path(value) / name) if value else name
    path = safe_ablage_path(speicherort, relative)
    path.mkdir(parents=True, exist_ok=True)
    return path
