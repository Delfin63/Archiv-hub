"""Scan-Quellen des Archiv-Hub.

Die Quellen liegen in ``data/scanner.json`` (nicht in ``app/config``), damit
``deploy-synology.sh`` sie nicht überschreibt. Der Standardeintrag ist
``kamera`` (die Bilder kommen aus dem Browser).

Weitere Quellen werden in ``data/scanner.json`` ergänzt; die ``/scan``-Seite
und die Pipeline (Texterkennung, Klassifizierung, Ablage) bleiben unverändert.
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
