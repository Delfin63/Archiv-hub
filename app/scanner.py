"""Scan-Quellen des Archiv-Hub.

Die Quellen liegen in ``data/scanner.json`` (nicht in ``app/config``), damit
``deploy-synology.sh`` sie nicht überschreibt. Der Standardeintrag ist
``kamera`` (die Bilder kommen aus dem Browser).

Die Typen:

``kamera``     Bilder kommen aus dem Browser.
``netzwerk``   Der Hub scannt selbst über eSCL (siehe scanner_escl.py).
``scan-app``   USB-Scanner, die der Hub nicht erreicht (er läuft im Container
               ohne USB). Beim Scannen öffnet der Mac die App "Scan"; die
               fertige Datei landet im Eingangskorb (siehe Skript 69).

Diese Liste wird von ``GET /api/scanner`` ausgeliefert. Ansteuern lässt sich
nur ``netzwerk``; ``scan-app`` ist ein Verweis auf den Weg über macOS.
"""

import json

from . import config


class ScanQuelle:
    """Eine Scan-Quelle.

    ``id`` ist der stabile Kurzname, ``name`` die Anzeige und ``typ`` steuert
    das Verhalten im Frontend (z. B. ``kamera`` für eine Dateiauswahl aus dem
    Browser bzw. der Handy-Kamera).
    """

    def __init__(self, id, name, typ):
        self.id = id
        self.name = name
        self.typ = typ

    def to_dict(self):
        return {"id": self.id, "name": self.name, "typ": self.typ}


# Registrierte Quelle "kamera": Bilder kommen aus dem Browser.
KAMERA = ScanQuelle("kamera", "Handy-Kamera / Fotos", "kamera")

# Typ eines Geräts, dessen Scan der Mac in der App "Scan" auslöst.
TYP_SCAN_APP = "scan-app"

DEFAULT_QUELLEN = [KAMERA]


def scanner_path():
    return config.DATA_DIR / "scanner.json"


def load_scanner():
    """Liefert die Quellen aus ``data/scanner.json``.

    Fehlt die Datei oder ist sie leer/ungültig, wird die Standardquelle
    ``kamera`` zurückgegeben.
    """
    path = scanner_path()
    quellen = []
    if path.is_file():
        try:
            data = json.loads(path.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            data = []
        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict) or not item.get("id"):
                    continue
                quellen.append(
                    ScanQuelle(
                        str(item["id"]),
                        str(item.get("name") or item["id"]),
                        str(item.get("typ") or "kamera"),
                    )
                )

    if not quellen:
        quellen = [ScanQuelle(q.id, q.name, q.typ) for q in DEFAULT_QUELLEN]
    return quellen


def finde_scan_app(geraet_id=None):
    """Liefert ein Gerät vom Typ ``scan-app`` oder None.

    Solche Geräte kann der Hub nicht selbst ansteuern: Sie hängen per USB
    oder über einen herstellereigenen Treiber am Mac, den der Container nicht
    erreicht. Der Scan läuft deshalb in der macOS-App "Scan"
    (Skript 69-archiv-hub-scansnap-helfer.command).

    Ohne ``geraet_id`` kommt das erste Gerät dieses Typs zurück.
    """
    for quelle in load_scanner():
        if quelle.typ != TYP_SCAN_APP:
            continue
        if geraet_id is None or quelle.id == geraet_id:
            return quelle
    return None
