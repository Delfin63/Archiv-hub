"""Flask-Backend des Archiv-Hub.

Stellt die Kern-Pipeline als HTTP-Endpunkte bereit:
  - POST /login               Passwort-Login (Session-Cookie, Passwort-Hash)
  - GET  /login               HTML-Anmeldeformular
  - POST /logout
  - GET  /einstellungen/ziele Verwaltungsoberfläche (hinter dem Login)
  - POST /api/upload          PDF/Bild entgegennehmen, OCR, klassifizieren, ablegen
  - CRUD /api/ziele, /api/ablage/ordner (hinter dem Login)

Der Passwortschutz folgt dem Muster des healing-hub (Flask-Session +
werkzeug.check_password_hash, Passwort-Hash aus ARCHIV_HUB_PASSWORD_HASH,
kein Klartext).
"""

import hashlib
import hmac
import os
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash

from . import classifier, config, ocr, pipeline, scanner, scanner_escl, storage

app = Flask(__name__)
app.secret_key = os.environ.get("ARCHIV_HUB_SECRET_KEY") or secrets.token_hex(32)
app.config["PASSWORD_HASH"] = (os.environ.get("ARCHIV_HUB_PASSWORD_HASH") or "").strip()
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024  # 200 MB
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("ARCHIV_HUB_COOKIE_SECURE", "0") == "1"

DATA_DIR = config.DATA_DIR
REVIEW_DIR = DATA_DIR / "zur-pruefung"
LOG_PATH = DATA_DIR / "archiv.log"

ALLOWED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
}

# Offen zugänglich: Anmeldung, Abmeldung und Liveness-Prüfung.
_OPEN_ENDPOINTS = {"login", "logout", "health"}

# Stabil über Neustarts hinweg, abgeleitet aus Secret und Passwort-Hash.
SESSION_GENERATION = hashlib.sha256(
    (
        "archiv-hub-session\0"
        + app.secret_key
        + "\0"
        + app.config["PASSWORD_HASH"]
    ).encode("utf-8")
).hexdigest()


def _read_version():
    try:
        return (
            (Path(__file__).resolve().parent / "version.txt")
            .read_text(encoding="utf-8")
            .strip()
        )
    except OSError:
        return ""


@app.context_processor
def inject_app_version():
    return {"app_version": _read_version(), "csrf_token": _csrf_token()}


def _is_authenticated():
    return (
        session.get("authenticated") is True
        and session.get("session_generation") == SESSION_GENERATION
    )


def _csrf_token():
    """Liefert das CSRF-Token der aktuellen Sitzung (erzeugt es bei Bedarf)."""
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _csrf_ok():
    """Prüft das CSRF-Token aus Formularfeld oder Header.

    Das Token wird bei jeder Sitzung neu erzeugt und nie in einem Cookie
    gespeichert, das ein fremder Ursprung setzen könnte (Double-Submit wäre
    fälschbar). Vergleich mit konstanter Laufzeit über hmac.compare_digest.
    """
    expected = session.get("csrf_token") or ""
    if not expected:
        return False
    sent = (
        request.form.get("csrf_token")
        or request.headers.get("X-CSRF-Token")
        or ""
    )
    return hmac.compare_digest(expected, sent)


@app.before_request
def require_login():
    if _is_authenticated():
        # CSRF nur für zustandsändernde Methoden prüfen.
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            if not _csrf_ok():
                if request.path.startswith("/api/"):
                    return (
                        jsonify({"ok": False, "error": "Ungültiges CSRF-Token."}),
                        403,
                    )
                return "Ungültiges CSRF-Token.", 403
        return None
    if session.get("authenticated"):
        session.clear()
    if request.endpoint in _OPEN_ENDPOINTS:
        return None
    # Statische Dateien (CSS/JS/Bilder) müssen auch auf der Anmeldeseite
    # erreichbar sein, sonst lädt die Login-Seite ohne Styling und Skripte.
    if request.path.startswith("/static/"):
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "Nicht angemeldet."}), 401
    return redirect("/login")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "service": "archiv-hub"})


@app.route("/login", methods=["GET", "POST"])
def login():
    if _is_authenticated():
        if request.method == "GET":
            return redirect("/")
        return jsonify({"ok": True, "next": "/"})

    if request.method == "GET":
        return render_template("login.html")

    password = request.form.get("password") or ""
    password_hash = app.config["PASSWORD_HASH"]
    if not password_hash:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": (
                        "Passwortschutz ist nicht konfiguriert. Bitte "
                        "ARCHIV_HUB_PASSWORD_HASH setzen."
                    ),
                }
            ),
            500,
        )
    if check_password_hash(password_hash, password):
        session.clear()
        session["authenticated"] = True
        session["session_generation"] = SESSION_GENERATION
        return jsonify({"ok": True, "next": "/"})
    return jsonify({"ok": False, "error": "Falsches Passwort."}), 401


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/")
def index():
    return render_template("index.html", active="index")


# ---------------------------------------------------------------------------
# Ablageorte (Verwaltung)
#
# Die Startseite deckt den normalen Ablauf ab. Diese Seite bleibt für das
# Anlegen und Bearbeiten benannter Ablageorte erreichbar; sie ist nicht mehr
# im Menü verlinkt, damit der Ablauf ohne Seitenwechsel auskommt.
# ---------------------------------------------------------------------------

@app.route("/einstellungen/ziele")
def ziele_page():
    return render_template("ziele.html", active="ziele")


@app.route("/api/hubs")
def api_hubs():
    return jsonify({"ok": True, "hubs": config.get_hubs()})


@app.route("/api/speicherorte")
def api_speicherorte():
    return jsonify({"ok": True, "speicherorte": storage.locations()})


@app.route("/api/scanner")
def api_scanner():
    return jsonify({"ok": True, "scanner": [q.to_dict() for q in scanner.load_scanner()]})


@app.route("/api/scanner/status")
def api_scanner_status():
    """Zustand des Netzwerk-Scanners (eSCL)."""
    url = config.scanner_url()
    if not url:
        return jsonify(
            {
                "ok": True,
                "konfiguriert": False,
                "name": "Scanner",
                "bereit": False,
                "zustand": "nicht eingerichtet",
            }
        )
    try:
        zustand = scanner_escl.status(url)
    except scanner_escl.ScannerFehler as exc:
        return jsonify(
            {
                "ok": True,
                "konfiguriert": True,
                "name": config.scanner_name(),
                "bereit": False,
                "zustand": str(exc),
            }
        )
    return jsonify(
        {
            "ok": True,
            "konfiguriert": True,
            "name": config.scanner_name(),
            "bereit": zustand["bereit"],
            "zustand": zustand["zustand"],
            "papier": zustand.get("papier", False),
        }
    )


def _jpeg_zu_png(daten):
    """Wandelt JPEG-Bytes in PNG-Bytes (der Scanner kann kein PNG)."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(daten)) as bild:
        ausgabe = io.BytesIO()
        bild.save(ausgabe, format="PNG")
        return ausgabe.getvalue()


@app.route("/api/scanner/scan", methods=["POST"])
def api_scanner_scan():
    """Scannt direkt über eSCL und legt das Ergebnis in den Eingangskorb."""
    url = config.scanner_url()
    if not url:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Kein Scanner eingerichtet. ARCHIV_HUB_SCANNER_URL setzen.",
                }
            ),
            400,
        )

    data = request.get_json(silent=True) or {}
    quelle = str(data.get("quelle") or "flachbett").strip()
    farbmodus = str(data.get("farbmodus") or "farbe").strip()
    duplex = bool(data.get("duplex"))
    # Der Scanner liefert PDF oder JPEG. PNG erzeugt der Hub daraus.
    ausgabeformat = str(data.get("format") or "pdf").strip().lower()
    if ausgabeformat not in ("pdf", "jpeg", "png"):
        return jsonify({"ok": False, "error": "Unbekanntes Format."}), 400
    try:
        aufloesung = int(data.get("aufloesung") or 300)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Ungültige Auflösung."}), 400

    # Der Scanner kennt nur PDF und JPEG – PNG wird danach umgewandelt.
    scanner_format = "jpeg" if ausgabeformat in ("jpeg", "png") else "pdf"

    try:
        daten, _typ = scanner_escl.scanne(
            url,
            quelle=quelle,
            aufloesung=aufloesung,
            farbmodus=farbmodus,
            duplex=duplex,
            format_=scanner_format,
        )
    except scanner_escl.ScannerFehler as exc:
        return jsonify({"ok": False, "error": str(exc)}), 502

    endung = {"pdf": ".pdf", "jpeg": ".jpg", "png": ".png"}[ausgabeformat]

    if ausgabeformat == "png":
        try:
            daten = _jpeg_zu_png(daten)
        except Exception as exc:  # noqa: BLE001
            return (
                jsonify({"ok": False, "error": f"PNG-Umwandlung fehlgeschlagen: {exc}"}),
                500,
            )

    korb = config.INPUT_DIR
    korb.mkdir(parents=True, exist_ok=True)

    # Sprechender Name: Scan_<Datum>_<Zeit>.<endung>, ohne zu überschreiben.
    stempel = config.jetzt().strftime("%Y-%m-%d_%H-%M-%S")
    name = f"Scan_{stempel}{endung}"
    ziel = korb / name
    zaehler = 2
    while ziel.exists():
        ziel = korb / f"Scan_{stempel} ({zaehler}){endung}"
        zaehler += 1

    ziel.write_bytes(daten)
    return jsonify(
        {
            "ok": True,
            "name": ziel.name,
            "groesse": len(daten),
            "aufloesung": aufloesung,
            "quelle": quelle,
        }
    )


# ---------------------------------------------------------------------------
# Eingangskorb
#
# Dateien im Eingangskorb (data/input) werden NICHT automatisch verarbeitet.
# Der Nutzer sieht sie in der Oberfläche, prüft sie und stösst die Verarbeitung
# einzeln an. Nach erfolgreicher Ablage wandert das Original nach
# data/input/erledigt/ – es wird nie gelöscht (siehe storage.korb_erledigt).
# ---------------------------------------------------------------------------


@app.route("/api/upload-ablage", methods=["POST"])
def upload_ablage():
    """Legt eine hochgeladene Datei NUR in den Eingangskorb.

    Verarbeitet nichts: der Nutzer prüft die Datei erst in der Oberfläche und
    stösst die Verarbeitung dann selbst an. Damit verhält sich ein Upload wie
    ein Scan, der in data/input abgelegt wird.
    """
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Keine Datei übergeben."}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "Leere Datei."}), 400

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return jsonify({"ok": False, "error": "Nicht unterstütztes Dateiformat."}), 400

    original_name = Path(file.filename).name
    input_dir = config.INPUT_DIR
    input_dir.mkdir(parents=True, exist_ok=True)

    # Namen erhalten, aber nie ueberschreiben.
    ziel = input_dir / original_name
    zaehler = 2
    while ziel.exists():
        ziel = input_dir / f"{Path(original_name).stem} ({zaehler}){suffix}"
        zaehler += 1

    file.save(ziel)
    return jsonify({"ok": True, "name": ziel.name})


@app.route("/api/korb", methods=["GET"])
def api_korb():
    return jsonify(
        {
            "ok": True,
            "dateien": storage.list_korb(),
            # Host-Pfad nur zur Anzeige / für den Finder-Link auf dem Mac.
            "host_pfad": config.korb_host_pfad(),
        }
    )


@app.route("/api/korb/<path:name>", methods=["DELETE"])
def api_korb_loeschen(name):
    """Entfernt eine Datei aus dem Korb (nach data/input/erledigt)."""
    ziel = storage.korb_erledigt(name)
    if ziel is None:
        return jsonify({"ok": False, "error": "Datei nicht gefunden."}), 404
    return jsonify({"ok": True, "verschoben_nach": str(ziel)})


@app.route("/api/zur-pruefung")
def api_zur_pruefung():
    files = []
    if REVIEW_DIR.is_dir():
        for path in sorted(REVIEW_DIR.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_file():
                continue
            stat = path.stat()
            files.append(
                {
                    "name": path.name,
                    "groesse": stat.st_size,
                    "geaendert": datetime.fromtimestamp(stat.st_mtime).isoformat(
                        timespec="seconds"
                    ),
                }
            )
    return jsonify({"ok": True, "dateien": files})


@app.route("/api/ziele", methods=["GET", "POST"])
def api_ziele():
    if request.method == "GET":
        return jsonify({"ok": True, "ziele": storage.load_ziele()})

    data = request.get_json(silent=True) or {}
    ziel = _normalize_ziel(data)
    # Nur der Name ist Pflicht. Ein leerer Pfad ist zulässig und bedeutet
    # "direkt im Wurzelordner des Speicherorts".
    if not ziel.get("name"):
        return jsonify({"ok": False, "error": "Name fehlt."}), 400
    speicherort = ziel.get("speicherort") or "standard"
    if not storage.is_known_speicherort(speicherort):
        return (
            jsonify(
                {
                    "ok": False,
                    "error": f"Unbekannter Speicherort: {speicherort!r}.",
                }
            ),
            400,
        )
    ziel["speicherort"] = speicherort

    ziele = storage.load_ziele()
    ziel["id"] = storage.new_id()
    ziele.append(ziel)
    storage.save_ziele(ziele)
    return jsonify({"ok": True, "ziel": ziel})


@app.route("/api/ziele/<ziel_id>", methods=["PUT", "DELETE"])
def api_ziel_detail(ziel_id):
    ziele = storage.load_ziele()
    ziel = storage.find_target(ziele, ziel_id)
    if ziel is None:
        return jsonify({"ok": False, "error": "Ziel nicht gefunden."}), 404

    if request.method == "DELETE":
        storage.save_ziele([z for z in ziele if z.get("id") != ziel_id])
        return jsonify({"ok": True})

    data = request.get_json(silent=True) or {}
    updated = _normalize_ziel(data, ziel)
    updated["id"] = ziel_id
    speicherort = updated.get("speicherort") or "standard"
    if not storage.is_known_speicherort(speicherort):
        return jsonify({"ok": False, "error": "Unbekannter Speicherort."}), 400
    updated["speicherort"] = speicherort
    storage.save_ziele(
        [updated if z.get("id") == ziel_id else z for z in ziele]
    )
    return jsonify({"ok": True, "ziel": updated})


@app.route("/api/ablage/ordner", methods=["GET", "POST"])
def api_ablage_ordner():
    if request.method == "GET":
        speicherort = request.args.get("speicherort") or "standard"
        pfad = request.args.get("pfad") or ""
        if not storage.is_known_speicherort(speicherort):
            return jsonify({"ok": False, "error": "Unbekannter Speicherort."}), 400
        try:
            ordner, mehr = storage.list_folders(speicherort, pfad)
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True, "ordner": ordner, "mehr": mehr})

    data = request.get_json(silent=True) or {}
    speicherort = str(data.get("speicherort") or "standard").strip()
    pfad = str(data.get("pfad") or "").strip()
    name = str(data.get("name") or "").strip()
    if not storage.is_known_speicherort(speicherort):
        return jsonify({"ok": False, "error": "Unbekannter Speicherort."}), 400
    try:
        storage.create_folder(speicherort, pfad, name)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True})


@app.route("/api/ablage/ordner-liste")
def api_ablage_ordner_liste():
    """Alle Ordner aller Speicherorte - für die Auswahl auf der Startseite.

    Liefert je Speicherort die Ordner der obersten Ebene. Der eingebaute
    Test-Speicherort "standard" wird ausgelassen, sobald ein echter
    Speicherort eingerichtet ist - er liegt im Projektordner und ist nicht
    als Ablage für echte Dokumente gedacht.
    """
    orte = storage.locations()
    echte = [o for o in orte if o.get("name") != storage.DEFAULT_SPEICHERORT]
    if echte:
        orte = echte

    ergebnis = []
    for loc in orte:
        name = loc.get("name")
        try:
            ordner, _mehr = storage.list_folders(name, "")
        except (ValueError, OSError):
            ordner = []
        ergebnis.append(
            {
                "speicherort": name,
                "label": loc.get("label") or name,
                "host_pfad": loc.get("host_pfad") or "",
                "ordner": ordner,
            }
        )
    return jsonify({"ok": True, "speicherorte": ergebnis})


@app.route("/api/korb/<path:name>/ablegen", methods=["POST"])
def api_korb_ablegen(name):
    """Legt eine Korb-Datei direkt in einen Ordner ab.

    JSON: {"speicherort": "...", "pfad": "...", "unterordner": "...",
           "dateiname": "..."}
    Der Unterordner wird bei Bedarf angelegt. Es ist KEIN vorher angelegtes
    Ziel nötig - der Ablageort wird direkt bestimmt. Der Dateiname ist ein
    Vorschlag der KI und kann vom Nutzer überschrieben werden.
    """
    quelle = storage.korb_datei(name)
    if quelle is None:
        return jsonify({"ok": False, "error": "Datei nicht gefunden."}), 404

    data = request.get_json(silent=True) or {}
    speicherort = str(data.get("speicherort") or "").strip()
    pfad = str(data.get("pfad") or "").strip()
    unterordner = str(data.get("unterordner") or "").strip()
    dateiname_vorgabe = str(data.get("dateiname") or "").strip()

    if not storage.is_known_speicherort(speicherort):
        return jsonify({"ok": False, "error": "Unbekannter Speicherort."}), 400

    # Neuen Unterordner bei Bedarf anlegen.
    if unterordner:
        try:
            storage.create_folder(speicherort, pfad, unterordner)
        except ValueError as exc:
            return (
                jsonify({"ok": False, "error": f"Ordner: {exc}"}),
                400,
            )
        pfad = str(Path(pfad) / unterordner) if pfad else unterordner

    try:
        ziel_ordner = storage.safe_ablage_path(speicherort, pfad)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    # Fehlt der Ordner noch, wird er angelegt: der Vorschlag der KI darf
    # einen neuen Ordnernamen enthalten, der erst jetzt entsteht.
    if pfad and not ziel_ordner.is_dir():
        try:
            storage.safe_ablage_path(speicherort, str(Path(pfad).parent))
            ziel_ordner.mkdir(parents=True, exist_ok=True)
        except (ValueError, OSError) as exc:
            return (
                jsonify({"ok": False, "error": f"Ordner konnte nicht angelegt werden: {exc}"}),
                400,
            )

    # Bilder bleiben Bilder: nur PDF wird durchsuchbar gemacht. Sonst würde
    # ein bewusst als JPEG/PNG abgelegter Scan stillschweigend zum PDF.
    quelle_endung = Path(quelle.name).suffix.lower()
    ist_bild = quelle_endung in (".jpg", ".jpeg", ".png", ".tif", ".tiff",
                                 ".bmp", ".webp")
    endung = quelle_endung if ist_bild else ".pdf"
    if endung == ".jpeg":
        endung = ".jpg"

    work_dir = DATA_DIR / "work" / secrets.token_hex(8)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        if ist_bild:
            # Kein OCR-Zwang: Original kopieren, Text nur zur Information lesen.
            ablage_datei = quelle
            try:
                _pdf, _text = ocr.process(quelle, work_dir)
            except Exception:  # noqa: BLE001
                pass  # ohne Texterkennung trotzdem ablegen
        else:
            try:
                ablage_datei, _text = ocr.process(quelle, work_dir)
            except Exception as exc:  # noqa: BLE001
                return (
                    jsonify(
                        {"ok": False, "error": f"Texterkennung fehlgeschlagen: {exc}"}
                    ),
                    500,
                )

        ziel_ordner.mkdir(parents=True, exist_ok=True)
        # Dateiname: Vorgabe des Nutzers (oder der KI), sonst Datum + Name.
        if dateiname_vorgabe:
            dateiname = pipeline.safe_filename(dateiname_vorgabe, endung=endung)
        else:
            stamm = Path(quelle.name).stem
            datum = config.jetzt().strftime("%Y-%m-%d")
            dateiname = pipeline.safe_filename(f"{datum} – {stamm}", endung=endung)
        ziel = pipeline.unique_destination(ziel_ordner, dateiname)
        shutil.copyfile(str(ablage_datei), str(ziel))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    # Original nach erledigt/ (es wird nie gelöscht).
    storage.korb_erledigt(quelle.name)

    pipeline.append_log(
        LOG_PATH,
        {
            "timestamp": config.jetzt().isoformat(timespec="seconds"),
            "original_filename": quelle.name,
            "status": "abgelegt",
            "ziel": str(ziel),
            "grund": None,
        },
    )
    return jsonify({"ok": True, "status": "abgelegt", "ziel": str(ziel)})


def _normalize_ziel(payload, existing=None):
    ziel = dict(existing or {})
    if "name" in payload:
        ziel["name"] = str(payload.get("name") or "").strip()
    if "pfad" in payload:
        ziel["pfad"] = str(payload.get("pfad") or "").strip()
    if "speicherort" in payload:
        ziel["speicherort"] = (
            str(payload.get("speicherort") or "").strip() or "standard"
        )
    if "beschreibung" in payload:
        ziel["beschreibung"] = str(payload.get("beschreibung") or "").strip()
    if "hub" in payload:
        ziel["hub"] = str(payload.get("hub") or "").strip() or None
    if "jahresordner" in payload:
        ziel["jahresordner"] = bool(payload.get("jahresordner"))
    if "aktiv" in payload:
        ziel["aktiv"] = bool(payload.get("aktiv"))
    return ziel


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def _move_to_review(searchable_pdf, original_name):
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    filename = Path(original_name).stem + ".pdf"
    destination = pipeline.unique_destination(REVIEW_DIR, filename)
    shutil.move(str(searchable_pdf), str(destination))
    return destination


@app.route("/api/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "Keine Datei übergeben."}), 400

    file = request.files["file"]
    if not file or not file.filename:
        return jsonify({"ok": False, "error": "Leere Datei."}), 400

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        return jsonify({"ok": False, "error": "Nicht unterstütztes Dateiformat."}), 400

    original_name = Path(file.filename).name
    input_dir = config.INPUT_DIR
    input_dir.mkdir(parents=True, exist_ok=True)

    token = secrets.token_hex(8)
    staged = input_dir / f"{token}{suffix}"
    file.save(staged)

    response, status = _verarbeite_datei(staged, original_name)
    # Der Eingangskorb behält Uploads nicht: die Datei ist nur zum Verarbeiten
    # hierher kopiert worden. Korb-Dateien werden dagegen nach erledigt/
    # verschoben (siehe api_korb_verarbeiten).
    staged.unlink(missing_ok=True)
    return jsonify(response), status


@app.route("/api/korb/<path:name>/vorschlag", methods=["POST"])
def api_korb_vorschlag(name):
    """Analysiert eine Korb-Datei und schlägt Ordner und Dateinamen vor.

    Legt NICHTS ab. Die KI darf einen vorhandenen Ordner wählen oder einen
    neuen Namen vorschlagen. Beides ist nur ein Vorschlag – der Nutzer
    bestätigt oder ändert ihn.
    """
    quelle = storage.korb_datei(name)
    if quelle is None:
        return jsonify({"ok": False, "error": "Datei nicht gefunden."}), 404

    ziele = storage.active_targets()

    # Zusätzliche Ordnernamen im Archiv, die (noch) kein Ziel sind.
    vorhandene = []
    for loc in storage.locations():
        try:
            ordner, _mehr = storage.list_folders(loc.get("name"), "")
        except (ValueError, OSError):
            ordner = []
        vorhandene.extend(ordner)
    vorhandene = sorted(set(vorhandene))

    work_dir = DATA_DIR / "work" / secrets.token_hex(8)
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        try:
            _searchable_pdf, text = ocr.process(quelle, work_dir)
        except Exception as exc:  # noqa: BLE001
            return (
                jsonify({"ok": False, "error": f"Texterkennung fehlgeschlagen: {exc}"}),
                500,
            )

        try:
            result = classifier.classify(text, ziele, vorhandene) or {}
        except Exception as exc:  # noqa: BLE001
            return (
                jsonify(
                    {"ok": False, "error": f"Klassifizierung fehlgeschlagen: {exc}"}
                ),
                502,
            )
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)

    # Vorhandener Ordner getroffen?
    ziel = storage.find_active_target(result.get("ziel_id"))
    ordner_name = str(result.get("ordner") or "").strip()
    if ziel is not None:
        ordner_name = str(ziel.get("name") or ordner_name).strip()
    elif not ordner_name:
        # Kein brauchbarer Name von der KI: aus dem Dokumenttyp ableiten.
        ordner_name = str(result.get("dokumenttyp") or "").strip() or "Sonstiges"

    # Ordnernamen für die Verzeichnisbildung entschärfen.
    ordner_name = pipeline.safe_ordnername(ordner_name)

    unsicher = pipeline.should_review(result, config.CONFIDENCE_THRESHOLD)

    # Scandatum als Rückfall, wenn das Dokument kein Datum enthält.
    fallback = config.jetzt().strftime("%Y-%m-%d")
    dateiname = pipeline.output_filename(
        result, quelle.name, fallback_datum=fallback, ordner=ordner_name
    )

    # Speicherort: bevorzugt der des getroffenen Ziels, sonst der erste
    # eingerichtete Speicherort.
    orte = storage.locations()
    speicherort = None
    if ziel is not None:
        speicherort = ziel.get("speicherort")
    if not speicherort and orte:
        echte = [o for o in orte if o.get("name") != storage.DEFAULT_SPEICHERORT]
        speicherort = (echte[0] if echte else orte[0]).get("name")

    return jsonify(
        {
            "ok": True,
            "vorschlag": {
                "ziel_id": (ziel or {}).get("id"),
                "ordner": ordner_name,
                "ordner_vorhanden": ziel is not None,
                "speicherort": speicherort,
                "dateiname": dateiname,
                "datum": result.get("datum") or "",
                "datum_aus_dokument": bool(str(result.get("datum") or "").strip()),
                "absender": result.get("absender"),
                "dokumentname": result.get("dokumentname") or "",
                "dokumenttyp": result.get("dokumenttyp"),
                "sicherheit": result.get("sicherheit"),
            },
            "unsicher": bool(unsicher),
            "vorhandene_ordner": vorhandene,
        }
    )


@app.route("/api/korb/<path:name>/verarbeiten", methods=["POST"])
def api_korb_verarbeiten(name):
    """Verarbeitet eine Datei aus dem Eingangskorb.

    Optional kann ein Ziel vorgegeben werden (JSON: {"ziel_id": "..."}). Dann
    wird die KI-Klassifizierung übersprungen und direkt in dieses Ziel gelegt.
    Ohne Vorgabe entscheidet die Klassifizierung wie beim Upload.
    """
    quelle = storage.korb_datei(name)
    if quelle is None:
        return jsonify({"ok": False, "error": "Datei nicht gefunden."}), 404

    vorgabe = None
    if request.is_json:
        vorgabe = (request.get_json(silent=True) or {}).get("ziel_id") or None

    response, status = _verarbeite_datei(quelle, quelle.name, ziel_id_vorgabe=vorgabe)

    # Variante C: das Original wird nie gelöscht, sondern nach erledigt/
    # verschoben – und zwar nur, wenn die Verarbeitung erfolgreich war.
    if status == 200 and response.get("ok"):
        storage.korb_erledigt(quelle.name)

    return jsonify(response), status


def _verarbeite_datei(staged, original_name, ziel_id_vorgabe=None):
    """OCR, Klassifizierung und Ablage einer bereits vorliegenden Datei.

    Liefert (response_dict, http_status). Der Aufrufer ist dafür
    verantwortlich, die Quelldatei zu entfernen bzw. wegzulegen.
    """
    suffix = staged.suffix.lower()
    token = secrets.token_hex(8)
    work_dir = DATA_DIR / "work" / token
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        try:
            searchable_pdf, text = ocr.process(staged, work_dir)
        except Exception as exc:  # noqa: BLE001
            return (
                {"ok": False, "error": f"Texterkennung fehlgeschlagen: {exc}"},
                500,
            )

        ziele = storage.active_targets()

        result = None
        error = None
        if ziel_id_vorgabe:
            # Vom Nutzer vorgegebenes Ziel: keine KI nötig. Datum/Absender
            # bleiben leer, der Dateiname wird entsprechend schlicht.
            ziel = storage.find_active_target(ziel_id_vorgabe)
            if ziel is None:
                return (
                    {"ok": False, "error": "Das gewählte Ziel ist nicht aktiv."},
                    400,
                )
            result = {
                "ziel_id": ziel_id_vorgabe,
                "datum": config.jetzt().strftime("%Y-%m-%d"),
                "absender": None,
                "dokumenttyp": None,
                "sicherheit": None,
            }
        elif not ziele:
            error = "Keine aktiven Ziele angelegt."
        else:
            try:
                result = classifier.classify(text, ziele)
            except Exception as exc:  # noqa: BLE001
                result = None
                error = f"Klassifizierung fehlgeschlagen: {exc}"

        entry = {
            "timestamp": config.jetzt().isoformat(timespec="seconds"),
            "original_filename": original_name,
            "status": "zur_pruefung",
            "ziel": None,
            "grund": None,
        }

        ziel = None
        unbekannter_speicherort = None
        if result is not None and (
            ziel_id_vorgabe
            or not pipeline.should_review(result, config.CONFIDENCE_THRESHOLD)
        ):
            ziel = storage.find_active_target(result.get("ziel_id"))
            if ziel is not None and not storage.is_known_speicherort(
                ziel.get("speicherort")
            ):
                unbekannter_speicherort = ziel.get("speicherort")
                ziel = None

        if ziel is None:
            destination = _move_to_review(searchable_pdf, original_name)
            entry["ziel"] = str(destination)
            if error:
                entry["grund"] = error
            elif result is None:
                entry["grund"] = "Klassifizierung fehlgeschlagen."
            elif unbekannter_speicherort:
                entry.update(_classification_fields(result))
                entry["grund"] = (
                    f"Unbekannter Speicherort: {unbekannter_speicherort!r}"
                )
            else:
                entry.update(_classification_fields(result))
                entry["grund"] = (
                    "Sicherheit unter der Schwelle, unbekannte ziel_id oder "
                    "unvollständige Angaben."
                )
        else:
            directory = storage.ziel_directory(ziel, result.get("datum"))
            directory.mkdir(parents=True, exist_ok=True)
            filename = pipeline.output_filename(
                result, original_name, ordner=ziel.get("name")
            )
            destination = pipeline.unique_destination(directory, filename)
            shutil.move(str(searchable_pdf), str(destination))
            entry.update(_classification_fields(result))
            entry["status"] = "abgelegt"
            entry["ziel"] = str(destination)

        pipeline.append_log(LOG_PATH, entry)

        response = {
            "ok": True,
            "status": entry["status"],
            "ziel": entry["ziel"],
            "original_filename": original_name,
        }
        if result:
            response["sicherheit"] = result.get("sicherheit")
            response["dokumenttyp"] = result.get("dokumenttyp")
            response["absender"] = result.get("absender")
            response["datum"] = result.get("datum")
            response["ziel_id"] = result.get("ziel_id")
        return response, 200
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _classification_fields(result):
    """Kopiert die Klassifizierungsfelder in den Log-Eintrag."""
    return {
        "ziel_id": result.get("ziel_id"),
        "datum": result.get("datum"),
        "absender": result.get("absender"),
        "dokumenttyp": result.get("dokumenttyp"),
        "sicherheit": result.get("sicherheit"),
    }
