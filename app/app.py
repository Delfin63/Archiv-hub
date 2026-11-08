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

from . import classifier, config, ocr, pipeline, scanner, storage

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


@app.route("/scan")
def scan_page():
    return render_template("scan.html", active="scan")


# ---------------------------------------------------------------------------
# Verwaltungsoberfläche
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
    if not ziel.get("name") or not ziel.get("pfad"):
        return jsonify({"ok": False, "error": "Name und Pfad sind Pflicht."}), 400
    speicherort = ziel.get("speicherort") or "standard"
    if not storage.is_known_speicherort(speicherort):
        return jsonify({"ok": False, "error": "Unbekannter Speicherort."}), 400
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

    work_dir = DATA_DIR / "work" / token
    work_dir.mkdir(parents=True, exist_ok=True)

    searchable_pdf = None
    try:
        try:
            searchable_pdf, text = ocr.process(staged, work_dir)
        except Exception as exc:  # noqa: BLE001
            staged.unlink(missing_ok=True)
            shutil.rmtree(work_dir, ignore_errors=True)
            return (
                jsonify({"ok": False, "error": f"Texterkennung fehlgeschlagen: {exc}"}),
                500,
            )

        ziele = storage.active_targets()

        result = None
        error = None
        if not ziele:
            error = "Keine aktiven Ziele angelegt."
        else:
            try:
                result = classifier.classify(text, ziele)
            except Exception as exc:  # noqa: BLE001
                result = None
                error = f"Klassifizierung fehlgeschlagen: {exc}"

        entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "original_filename": original_name,
            "status": "zur_pruefung",
            "ziel": None,
            "grund": None,
        }

        ziel = None
        unbekannter_speicherort = None
        if result is not None and not pipeline.should_review(
            result, config.CONFIDENCE_THRESHOLD
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
            filename = pipeline.output_filename(result)
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
        return jsonify(response)
    finally:
        staged.unlink(missing_ok=True)
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
