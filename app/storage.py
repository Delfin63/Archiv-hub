"""Verwaltung der Ablage-Ziele, Speicherorte und der Pfadsicherheit.

Die Ziele (data/ziele.json) und Speicherorte (data/speicherorte.json) liegen
bewusst NICHT in app/config, sondern in data/, weil deploy-synology.sh nur den
Quellcode überträgt und data/ unangetastet lässt.
"""

import json
import re
import secrets
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
