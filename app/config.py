"""Konfiguration des Archiv-Hub.

Lädt app/config/settings.yaml und app/config/hubs.yaml sowie eine lokale
``.env``-Datei. Umgebungsvariablen, die bereits gesetzt sind, werden von der
``.env`` nicht überschrieben (gleiches Muster wie healing-hub/app/summarizer.py).
"""

import os
from pathlib import Path

import yaml

APP_DIR = Path(__file__).resolve().parent
PROJECT_DIR = APP_DIR.parent
CONFIG_DIR = APP_DIR / "config"


def _load_env_file():
    """Lädt eine lokale ``.env`` (Projektwurzel) ohne vorhandene Variablen zu
    überschreiben. Nur leere Werte werden aufgefüllt."""
    env_path = PROJECT_DIR / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key or os.environ.get(key):
            continue
        os.environ[key] = value.strip()


def _load_yaml(name):
    path = CONFIG_DIR / name
    if not path.is_file():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_load_env_file()

_settings = _load_yaml("settings.yaml")
_hubs = _load_yaml("hubs.yaml")

_llm = _settings.get("llm") or {}

DATA_DIR = Path(os.environ.get("ARCHIV_HUB_DATA_DIR", PROJECT_DIR / "data"))
INPUT_DIR = Path(
    os.environ.get(
        "ARCHIV_HUB_INPUT_DIR",
        _settings.get("input_dir") or (DATA_DIR / "input"),
    )
)
# Ablage-Basis im Container: /ablage. Darunter liegen die Speicherorte als
# /ablage/<name> (Docker-Volumes). Der HOST-Pfad des eingebauten Speicherorts
# "standard" wird per ARCHIV_HUB_ABLAGE_BASIS in compose.yaml gesetzt und hier
# nur zur Anzeige in den Container gereicht. Der absolute Pfad kommt als
# ARCHIV_HUB_ABLAGE_BASIS_ANZEIGE vom Startskript 60 bzw. deploy-synology.sh.
ABLAGE_BASIS = Path(os.environ.get("ARCHIV_HUB_ABLAGE_BASIS", "/ablage"))


def standard_host_pfad():
    """Host-Pfad des Standard-Speicherorts für die Anzeige.

    Bevorzugt den vom Startskript 60 bzw. deploy-synology.sh aufgelösten
    absoluten Pfad (ARCHIV_HUB_ABLAGE_BASIS_ANZEIGE). Fällt sonst auf den
    relativen Standardwert zurück.
    """
    return (
        os.environ.get("ARCHIV_HUB_ABLAGE_BASIS_ANZEIGE")
        or os.environ.get("ARCHIV_HUB_STANDARD_HOST_PFAD")
        or "./data/ablage"
    )


def korb_host_pfad():
    """HOST-Pfad des Eingangskorbs (data/input) für Anzeige und Finder-Link.

    Im Container ist das /app/data/input – dieser Pfad nützt auf dem Mac
    nichts. Das Startskript 60 bzw. deploy-synology.sh löst den echten Pfad
    auf und übergibt ihn als ARCHIV_HUB_KORB_HOST_PFAD.
    """
    return os.environ.get("ARCHIV_HUB_KORB_HOST_PFAD") or ""


STANDARD_HOST_PFAD = standard_host_pfad()
CONFIDENCE_THRESHOLD = float(_settings.get("confidence_threshold", 0.7))


def get_hubs():
    """Liefert die Hub-Liste aus hubs.yaml (optionale Gruppierung)."""
    return _hubs.get("hubs") or []


def get_llm_base_url():
    return os.environ.get(
        "DEEPSEEK_BASE_URL",
        _llm.get("base_url", "https://api.deepseek.com"),
    )


def get_llm_model():
    return os.environ.get(
        "DEEPSEEK_MODEL",
        _llm.get("model", "deepseek-v4-pro"),
    )
