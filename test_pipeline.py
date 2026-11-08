"""Tests für den Archiv-Hub (Pipeline, Sicherheit, Klassifizierung, Deploy).

Ausführung aus dem Projektverzeichnis:
    .venv/bin/python -m pytest test_pipeline.py -q
"""

import io
import json
import os
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import classifier, ocr, pipeline, storage  # noqa: E402

PROJECT_DIR = Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Klassifizierung: JSON-Extraktion und einmaliger Wiederholungsversuch
# ---------------------------------------------------------------------------

def test_extract_json_plain():
    assert classifier._extract_json('{"ziel_id": "z1"}') == {"ziel_id": "z1"}


def test_extract_json_fenced():
    raw = '```json\n{"ziel_id": "z1"}\n```'
    assert classifier._extract_json(raw) == {"ziel_id": "z1"}


def test_extract_json_invalid():
    with pytest.raises(ValueError):
        classifier._extract_json("das ist kein json")


def test_classify_retries_once_on_invalid_json(monkeypatch):
    calls = []

    def fake_chat(messages, temperature=0.1, max_tokens=1000):
        calls.append(list(messages))
        if len(calls) == 1:
            return "kein gültiges JSON"
        return (
            '{"ziel_id": "z1", "datum": "2026-11-07", '
            '"absender": "Arzt", "dokumenttyp": "Brief", "sicherheit": 0.9}'
        )

    monkeypatch.setattr(classifier, "_chat", fake_chat)

    ziele = [{"id": "z1", "name": "Healing", "beschreibung": "Arzt", "hub": "healing-hub"}]
    result = classifier.classify("Dokumenttext", ziele)

    assert result["ziel_id"] == "z1"
    assert result["sicherheit"] == 0.9
    assert len(calls) == 2


def test_classify_truncates_to_4000_chars(monkeypatch):
    captured = {}

    def fake_chat(messages, temperature=0.1, max_tokens=1000):
        captured["user"] = messages[-1]["content"]
        return '{"ziel_id": "z1"}'

    monkeypatch.setattr(classifier, "_chat", fake_chat)
    classifier.classify("x" * 6000, [{"id": "z1", "name": "Ziel"}])

    assert "x" * 6000 not in captured["user"]
    document_text = captured["user"].split("Dokumenttext:\n", 1)[1]
    assert len(document_text) == classifier.MAX_TEXT_CHARS


def test_classify_prompt_contains_only_active_target_ids(monkeypatch):
    captured = {}

    def fake_chat(messages, temperature=0.1, max_tokens=1000):
        captured["user"] = messages[-1]["content"]
        return '{"ziel_id": "z1"}'

    monkeypatch.setattr(classifier, "_chat", fake_chat)
    ziele = [
        {"id": "z1", "name": "Aktiv", "beschreibung": "b1", "hub": "healing-hub"},
        {"id": "z2", "name": "Zwei", "beschreibung": "b2", "hub": None},
    ]
    classifier.classify("text", ziele)

    assert "z1" in captured["user"]
    assert "z2" in captured["user"]


# ---------------------------------------------------------------------------
# Ablage-Prüfung
# ---------------------------------------------------------------------------

def test_should_review_missing_fields():
    assert pipeline.should_review({}, 0.7) is True


def test_should_review_neuer_ordner_ist_ok():
    """Die KI darf einen neuen Ordner vorschlagen (ziel_id "neu")."""
    result = {
        "ziel_id": "neu",
        "ordner": "Uebungsanleitungen",
        "datum": "",
        "absender": "",
        "dokumenttyp": "Uebungsanleitung",
        "sicherheit": 0.9,
    }
    assert pipeline.should_review(result, 0.7) is False


def test_should_review_low_confidence():
    result = {
        "ziel_id": "z1",
        "datum": "2026-11-07",
        "absender": "A",
        "dokumenttyp": "B",
        "sicherheit": 0.5,
    }
    assert pipeline.should_review(result, 0.7) is True


def test_should_not_review_complete_and_confident():
    result = {
        "ziel_id": "z1",
        "datum": "2026-11-07",
        "absender": "A",
        "dokumenttyp": "B",
        "sicherheit": 0.9,
    }
    assert pipeline.should_review(result, 0.7) is False


def test_should_review_invalid_date():
    result = {
        "ziel_id": "z1",
        "datum": "07.11.2026",
        "absender": "A",
        "dokumenttyp": "B",
        "sicherheit": 0.9,
    }
    assert pipeline.should_review(result, 0.7) is True


def test_output_filename():
    """Format: Datum – Ordnername – Dokumentname.pdf"""
    result = {"datum": "2026-11-07", "dokumentname": "Rechnung", "dokumenttyp": "Rechnung"}
    name = pipeline.output_filename(result, ordner="Rechnungen")
    assert name == "2026-11-07 – Rechnungen – Rechnung.pdf"


def test_unique_destination_appends_counter(tmp_path):
    (tmp_path / "a.pdf").write_text("vorhanden")
    assert pipeline.unique_destination(tmp_path, "a.pdf").name == "a (2).pdf"


def test_append_log_writes_json_line(tmp_path):
    log_path = tmp_path / "archiv.log"
    pipeline.append_log(log_path, {"status": "abgelegt", "ziel": "/tmp/x.pdf"})

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["status"] == "abgelegt"


# ---------------------------------------------------------------------------
# Pfadsicherheit (realpath, kein "..", kein Symlink-Ausbruch)
# ---------------------------------------------------------------------------

def test_safe_ablage_path_rejects_traversal(tmp_path, monkeypatch):
    import app.config as config

    ablage = tmp_path / "ablage"
    monkeypatch.setattr(config, "ABLAGE_BASIS", ablage)

    with pytest.raises(ValueError):
        storage.safe_ablage_path("standard", "../ausserhalb")


def test_safe_ablage_path_rejects_symlink_escape(tmp_path, monkeypatch):
    import app.config as config

    ablage = tmp_path / "ablage"
    (ablage / "standard").mkdir(parents=True)
    monkeypatch.setattr(config, "ABLAGE_BASIS", ablage)

    outside = tmp_path / "aussen"
    outside.mkdir()
    (ablage / "standard" / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError):
        storage.safe_ablage_path("standard", "link")


def test_safe_ablage_path_accepts_subfolder(tmp_path, monkeypatch):
    import app.config as config

    ablage = tmp_path / "ablage"
    monkeypatch.setattr(config, "ABLAGE_BASIS", ablage)

    assert storage.safe_ablage_path("standard", "healing") == (
        ablage / "standard" / "healing"
    ).resolve()


def test_safe_ablage_path_per_speicherort(tmp_path, monkeypatch):
    import app.config as config

    ablage = tmp_path / "ablage"
    monkeypatch.setattr(config, "ABLAGE_BASIS", ablage)

    assert storage.safe_ablage_path("owc", "dokumente") == (
        ablage / "owc" / "dokumente"
    ).resolve()
    with pytest.raises(ValueError):
        storage.safe_ablage_path("owc", "../standard")


def test_ziel_directory_jahresordner(tmp_path, monkeypatch):
    import app.config as config

    ablage = tmp_path / "ablage"
    monkeypatch.setattr(config, "ABLAGE_BASIS", ablage)

    ziel = {"pfad": "healing", "jahresordner": True, "speicherort": "standard"}
    assert storage.ziel_directory(ziel, "2026-11-07") == (
        ablage / "standard" / "healing" / "2026"
    ).resolve()


# ---------------------------------------------------------------------------
# Deploy überträgt data/ nicht
# ---------------------------------------------------------------------------

def test_deploy_does_not_transfer_data():
    content = (PROJECT_DIR / "deploy-synology.sh").read_text(encoding="utf-8")

    rsync_blocks = re.findall(r"rsync[^\n]*(?:\n[ \t]+[^\n]*)*", content)
    assert rsync_blocks, "deploy-synology.sh enthält keine rsync-Aufrufe"
    for block in rsync_blocks:
        assert "data/" not in block, f"data/ darf nicht rsync-Quelle sein: {block!r}"
        assert "ziele.json" not in block, f"ziele.json darf nicht rsync-Quelle sein: {block!r}"


# ---------------------------------------------------------------------------
# OCR (Fallback ohne OCRmyPDF: Textschicht eines durchsuchbaren PDFs)
# ---------------------------------------------------------------------------

def test_ocr_extracts_text_from_searchable_pdf(tmp_path):
    from reportlab.pdfgen import canvas

    pdf = tmp_path / "sample.pdf"
    c = canvas.Canvas(str(pdf))
    c.drawString(72, 720, "Rechnung Arztpraxis Muster")
    c.save()

    searchable, text = ocr.process(pdf, tmp_path / "work")

    assert searchable.exists()
    assert "Muster" in text


# ---------------------------------------------------------------------------
# End-to-End über die Flask-Route
# ---------------------------------------------------------------------------

def _sample_pdf_bytes():
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer)
    c.drawString(72, 720, "Rechnung von der Musterpraxis")
    c.save()
    return buffer.getvalue()


def _ziel(id="z1", pfad="healing", hub="healing-hub", jahresordner=False, aktiv=True, speicherort="standard"):
    return {
        "id": id,
        "name": "Ziel " + id,
        "speicherort": speicherort,
        "pfad": pfad,
        "beschreibung": "Arztunterlagen",
        "hub": hub,
        "jahresordner": jahresordner,
        "aktiv": aktiv,
    }


def _client_with_tmp_dirs(tmp_path, monkeypatch, classify_result, ziele):
    from werkzeug.security import generate_password_hash

    import app.app as appmod

    data_dir = tmp_path / "data"
    ablage_dir = tmp_path / "ablage"
    data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(appmod, "DATA_DIR", data_dir)
    monkeypatch.setattr(appmod, "REVIEW_DIR", data_dir / "zur-pruefung")
    monkeypatch.setattr(appmod, "LOG_PATH", data_dir / "archiv.log")
    monkeypatch.setattr(appmod.config, "DATA_DIR", data_dir)
    monkeypatch.setattr(appmod.config, "INPUT_DIR", data_dir / "input")
    monkeypatch.setattr(appmod.config, "ABLAGE_BASIS", ablage_dir)

    if ziele is not None:
        (data_dir / "ziele.json").write_text(json.dumps(ziele, ensure_ascii=False))

    if classify_result is not None:
        monkeypatch.setattr(
            appmod.classifier,
            "classify",
            lambda text, z: dict(classify_result),
        )

    appmod.app.config["PASSWORD_HASH"] = generate_password_hash("geheim")
    appmod.app.testing = True

    client = appmod.app.test_client()
    login = client.post("/login", data={"password": "geheim"})
    assert login.get_json()["ok"] is True

    # CSRF-Token der angemeldeten Sitzung setzen, damit zustandsändernde
    # Anfragen (POST/PUT/DELETE) nicht mit 403 abgewiesen werden.
    with client.session_transaction() as sess:
        sess["csrf_token"] = "test-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "test-csrf-token"

    return client, data_dir, ablage_dir


def _upload(client, filename="sample.pdf"):
    return client.post(
        "/api/upload",
        data={"file": (io.BytesIO(_sample_pdf_bytes()), filename)},
        content_type="multipart/form-data",
    )


def test_upload_files_confident_document(tmp_path, monkeypatch):
    result = {
        "ziel_id": "z1",
        "datum": "2026-11-07",
        "dokumentname": "Serverwartung",
        "absender": "Musterpraxis",
        "dokumenttyp": "Rechnung",
        "sicherheit": 0.95,
    }
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, result, [_ziel()]
    )

    response = _upload(client)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "abgelegt"

    expected = ablage_dir / "standard" / "healing" / "2026-11-07 – Ziel z1 – Serverwartung.pdf"
    assert expected.exists()

    log_line = (data_dir / "archiv.log").read_text(encoding="utf-8").strip()
    assert json.loads(log_line)["status"] == "abgelegt"


def test_upload_jahresordner_creates_year_subfolder(tmp_path, monkeypatch):
    result = {
        "ziel_id": "z1",
        "datum": "2026-11-07",
        "dokumentname": "Ueberweisung",
        "absender": "Arzt",
        "dokumenttyp": "Brief",
        "sicherheit": 0.9,
    }
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, result, [_ziel(jahresordner=True)]
    )

    response = _upload(client)
    assert response.get_json()["status"] == "abgelegt"

    expected = ablage_dir / "standard" / "healing" / "2026" / "2026-11-07 – Ziel z1 – Ueberweisung.pdf"
    assert expected.exists()


def test_upload_unknown_ziel_id_to_review(tmp_path, monkeypatch):
    result = {
        "ziel_id": "gibt-es-nicht",
        "datum": "2026-11-07",
        "absender": "A",
        "dokumenttyp": "B",
        "sicherheit": 0.9,
    }
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, result, [_ziel()]
    )

    response = _upload(client)
    assert response.get_json()["status"] == "zur_pruefung"
    assert (data_dir / "zur-pruefung" / "sample.pdf").exists()
    assert not (ablage_dir / "standard").exists()


def test_upload_unklar_to_review(tmp_path, monkeypatch):
    result = {
        "ziel_id": "unklar",
        "datum": "2026-11-07",
        "absender": "A",
        "dokumenttyp": "B",
        "sicherheit": 0.9,
    }
    client, data_dir, _ = _client_with_tmp_dirs(
        tmp_path, monkeypatch, result, [_ziel()]
    )

    response = _upload(client)
    assert response.get_json()["status"] == "zur_pruefung"
    assert (data_dir / "zur-pruefung" / "sample.pdf").exists()


def test_upload_inactive_ziel_to_review(tmp_path, monkeypatch):
    ziele = [_ziel(id="z1", aktiv=False), _ziel(id="z2", pfad="aktiv")]
    result = {
        "ziel_id": "z1",
        "datum": "2026-11-07",
        "absender": "A",
        "dokumenttyp": "B",
        "sicherheit": 0.9,
    }
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, result, ziele
    )

    response = _upload(client)
    assert response.get_json()["status"] == "zur_pruefung"
    assert (data_dir / "zur-pruefung" / "sample.pdf").exists()
    assert not (ablage_dir / "standard").exists()


def test_upload_no_targets_to_review(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )

    response = _upload(client)
    assert response.get_json()["status"] == "zur_pruefung"
    assert (data_dir / "zur-pruefung" / "sample.pdf").exists()
    assert list(ablage_dir.glob("*")) == []


def test_upload_requires_login(tmp_path):
    import app.app as appmod

    appmod.app.testing = True
    client = appmod.app.test_client()
    response = _upload(client)
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Ziel-CRUD (Löschen löscht nie Dateien/Ordner)
# ---------------------------------------------------------------------------

def test_delete_ziel_keeps_files(tmp_path, monkeypatch):
    from werkzeug.security import generate_password_hash

    import app.app as appmod

    data_dir = tmp_path / "data"
    ablage_dir = tmp_path / "ablage"
    data_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(appmod, "DATA_DIR", data_dir)
    monkeypatch.setattr(appmod.config, "DATA_DIR", data_dir)
    monkeypatch.setattr(appmod.config, "ABLAGE_BASIS", ablage_dir)
    (data_dir / "ziele.json").write_text(
        json.dumps([_ziel(id="z1", pfad="healing")], ensure_ascii=False)
    )

    appmod.app.config["PASSWORD_HASH"] = generate_password_hash("geheim")
    appmod.app.testing = True
    client = appmod.app.test_client()
    client.post("/login", data={"password": "geheim"})
    with client.session_transaction() as sess:
        sess["csrf_token"] = "test-csrf-token"
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "test-csrf-token"

    # Datei im Ablage-Ordner anlegen
    ziel_ordner = ablage_dir / "healing"
    ziel_ordner.mkdir(parents=True)
    (ziel_ordner / "dokument.pdf").write_text("x")

    response = client.delete("/api/ziele/z1")
    assert response.get_json()["ok"] is True

    # Ziel ist aus ziele.json entfernt ...
    ziele = json.loads((data_dir / "ziele.json").read_text(encoding="utf-8"))
    assert ziele == []

    # ... aber die Datei und der Ordner bleiben erhalten.
    assert (ziel_ordner / "dokument.pdf").exists()


# ---------------------------------------------------------------------------
# Browser-Seiten und Zugriffskontrolle
# ---------------------------------------------------------------------------

def test_html_page_redirects_to_login_without_login(tmp_path, monkeypatch):
    import app.app as appmod

    appmod.app.testing = True
    client = appmod.app.test_client()

    for url in ("/", "/einstellungen/ziele"):
        response = client.get(url)
        assert response.status_code == 302, url
        assert response.headers["Location"].endswith("/login"), url


def test_api_returns_401_json_without_login(tmp_path, monkeypatch):
    import app.app as appmod

    appmod.app.testing = True
    client = appmod.app.test_client()

    response = client.get("/api/ziele")
    assert response.status_code == 401
    assert response.get_json()["ok"] is False


def test_scanner_registriert_quelle_kamera():
    import app.scanner as scanner

    kamera = scanner.ScanQuelle("kamera", "Handy-Kamera / Fotos", "kamera")
    assert (kamera.id, kamera.name, kamera.typ) == (
        "kamera",
        "Handy-Kamera / Fotos",
        "kamera",
    )
    assert kamera.to_dict() == {
        "id": "kamera",
        "name": "Handy-Kamera / Fotos",
        "typ": "kamera",
    }

    quellen = scanner.load_scanner()
    ids = [q.id for q in quellen]
    assert "kamera" in ids


def test_api_scanner_liefert_kamera(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )

    response = client.get("/api/scanner")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    ids = [s["id"] for s in payload["scanner"]]
    assert ids == ["kamera"]
    assert payload["scanner"][0]["name"] == "Handy-Kamera / Fotos"
    assert payload["scanner"][0]["typ"] == "kamera"


def test_scanner_json_enthaelt_netzwerk_scanner():
    import app.scanner as scanner

    quellen = scanner.load_scanner()
    nach_id = {q.id: q for q in quellen}

    erwartet = {
        "canon-dx-6870i": "Canon Imagerunner Advanced DX 6870i",
        "brother-mfc-j6920dw": "Brother MFC-J6920DW",
        "brother-mfc-l2980dw": "Brother MFC-L2980DW",
        "epson-xp-5200": "Epson XP-5200 Series",
    }
    for sid, name in erwartet.items():
        assert sid in nach_id
        assert nach_id[sid].name == name
        assert nach_id[sid].typ == "netzwerk"


def test_api_scanner_liefert_alle_quellen(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )

    (data_dir / "scanner.json").write_text(
        json.dumps(
            [
                {"id": "kamera", "name": "Handy-Kamera / Fotos", "typ": "kamera"},
                {
                    "id": "canon-dx-6870i",
                    "name": "Canon Imagerunner Advanced DX 6870i",
                    "typ": "netzwerk",
                },
                {
                    "id": "brother-mfc-j6920dw",
                    "name": "Brother MFC-J6920DW",
                    "typ": "netzwerk",
                },
                {
                    "id": "brother-mfc-l2980dw",
                    "name": "Brother MFC-L2980DW",
                    "typ": "netzwerk",
                },
                {
                    "id": "epson-xp-5200",
                    "name": "Epson XP-5200 Series",
                    "typ": "netzwerk",
                },
            ],
            ensure_ascii=False,
        )
    )

    response = client.get("/api/scanner")
    assert response.status_code == 200
    ids = [s["id"] for s in response.get_json()["scanner"]]
    assert ids == [
        "kamera",
        "canon-dx-6870i",
        "brother-mfc-j6920dw",
        "brother-mfc-l2980dw",
        "epson-xp-5200",
    ]


def test_api_scanner_401_without_login(tmp_path, monkeypatch):
    import app.app as appmod

    appmod.app.testing = True
    client = appmod.app.test_client()

    response = client.get("/api/scanner")
    assert response.status_code == 401
    assert response.get_json()["ok"] is False


def test_login_flow_and_start_page(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )

    response = client.get("/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # Ablage-Werkzeug: Quelle waehlen, Vorschlag pruefen, ablegen.
    assert "Wie möchtest du ein Dokument hinzufügen?" in html
    assert "Scannen" in html
    assert "Hochladen" in html
    assert "Eingangskorb" in html
    # Die beiden Arbeitsbereiche der Schritte 4/5 (Ziel, Ausführen).
    assert "Ziel wählen" in html
    assert "Ausführen und ablegen" in html
    assert "Eingangskorb" in html
    assert "Zur Prüfung" in html


def test_ziele_page_renders_after_login(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )

    response = client.get("/einstellungen/ziele")
    assert response.status_code == 200
    assert "Ziele" in response.get_data(as_text=True)


def test_ziele_page_hat_kartenliste_statt_tabelle(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )

    html = client.get("/einstellungen/ziele").get_data(as_text=True)
    assert "<table" not in html
    assert 'id="ziele-liste"' in html
    assert "<h1>Ziele</h1>" not in html


def test_login_page_is_public(tmp_path, monkeypatch):
    import app.app as appmod

    appmod.app.testing = True
    client = appmod.app.test_client()

    response = client.get("/login")
    assert response.status_code == 200
    assert "Anmelden" in response.get_data(as_text=True)


def test_static_assets_are_public_without_login(tmp_path, monkeypatch):
    import app.app as appmod

    appmod.app.testing = True
    client = appmod.app.test_client()

    for pfad in ("/static/archiv.css", "/static/archiv.js", "/static/index.js"):
        response = client.get(pfad)
        assert response.status_code == 200, pfad


def test_zur_pruefung_lists_files(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )

    (data_dir / "zur-pruefung").mkdir(parents=True, exist_ok=True)
    (data_dir / "zur-pruefung" / "dok.pdf").write_text("x")

    response = client.get("/api/zur-pruefung")
    assert response.status_code == 200
    names = [d["name"] for d in response.get_json()["dateien"]]
    assert "dok.pdf" in names


def test_upload_response_includes_sicherheit(tmp_path, monkeypatch):
    result = {
        "ziel_id": "z1",
        "datum": "2026-11-07",
        "absender": "A",
        "dokumenttyp": "B",
        "sicherheit": 0.88,
    }
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, result, [_ziel()]
    )

    payload = _upload(client).get_json()
    assert payload["status"] == "abgelegt"
    assert payload["sicherheit"] == 0.88
    assert payload["original_filename"] == "sample.pdf"


def test_create_ziel_via_api(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )

    response = client.post(
        "/api/ziele",
        json={
            "name": "Healing",
            "pfad": "healing",
            "hub": "healing-hub",
            "beschreibung": "Arzt",
            "jahresordner": False,
            "aktiv": True,
        },
    )
    assert response.get_json()["ok"] is True

    ziele = client.get("/api/ziele").get_json()["ziele"]
    assert len(ziele) == 1
    assert ziele[0]["name"] == "Healing"
    assert ziele[0]["speicherort"] == "standard"


def test_folder_and_ziel_end_to_end(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )

    # Ordner anlegen
    r = client.post(
        "/api/ablage/ordner",
        json={"speicherort": "standard", "pfad": "healing", "name": "2026"},
    )
    assert r.get_json()["ok"] is True
    assert (ablage_dir / "standard" / "healing" / "2026").exists()

    # Ziel speichern
    r = client.post(
        "/api/ziele",
        json={
            "name": "Healing",
            "pfad": "healing",
            "hub": "healing-hub",
            "beschreibung": "Arzt",
            "jahresordner": True,
            "aktiv": True,
        },
    )
    assert r.get_json()["ok"] is True
    ziel_id = r.get_json()["ziel"]["id"]

    # Ziel erscheint in GET /api/ziele
    ziele = client.get("/api/ziele").get_json()["ziele"]
    assert any(z["id"] == ziel_id and z["name"] == "Healing" for z in ziele)


def test_page_scripts_are_valid_js():
    import shutil
    import subprocess
    import tempfile

    node = shutil.which("node")
    if node is None:
        pytest.skip("node nicht verfügbar")

    static_dir = PROJECT_DIR / "app" / "static"
    templates_dir = PROJECT_DIR / "app" / "templates"

    scripts = []
    for js in sorted(static_dir.rglob("*.js")):
        scripts.append(
            ("static: " + str(js.relative_to(static_dir)), js.read_text(encoding="utf-8"))
        )
    for tpl in sorted(templates_dir.rglob("*.html")):
        content = tpl.read_text(encoding="utf-8")
        for i, block in enumerate(re.findall(r"<script>(.*?)</script>", content, re.DOTALL)):
            scripts.append((f"template {tpl.name} block {i}", block))

    assert scripts, "keine Skripte gefunden"
    for name, source in scripts:
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(source)
            path = f.name
        try:
            result = subprocess.run(
                [node, "--check", path], capture_output=True, text=True
            )
            assert result.returncode == 0, f"{name}: {result.stderr}"
        finally:
            Path(path).unlink(missing_ok=True)


def test_archiv_css_hat_farbvariablen():
    css = (PROJECT_DIR / "app" / "static" / "archiv.css").read_text(encoding="utf-8")
    assert ":root" in css
    for var in ("--navy", "--blue", "--cyan", "--yellow", "--green", "--red", "--bg"):
        assert f"{var}:" in css


def test_archiv_css_verwendet_nur_definierte_variablen():
    """Jede var(--x) muss auch definiert sein, sonst wirkt die Regel nicht."""
    css = (PROJECT_DIR / "app" / "static" / "archiv.css").read_text(encoding="utf-8")
    definiert = set(re.findall(r"^\s*(--[a-z0-9-]+)\s*:", css, re.M))
    verwendet = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    fehlend = sorted(verwendet - definiert)
    assert not fehlend, f"Nicht definierte CSS-Variablen: {fehlend}"


def test_migration_speicherort_default(tmp_path, monkeypatch):
    import app.config as config

    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    (tmp_path / "ziele.json").write_text(
        json.dumps(
            [
                {
                    "id": "t1",
                    "name": "Test",
                    "pfad": "healing",
                    "hub": None,
                    "beschreibung": "",
                    "jahresordner": False,
                    "aktiv": True,
                }
            ],
            ensure_ascii=False,
        )
    )

    ziele = storage.load_ziele()
    assert ziele[0]["speicherort"] == "standard"

    saved = json.loads((tmp_path / "ziele.json").read_text(encoding="utf-8"))
    assert saved[0]["speicherort"] == "standard"


def test_upload_unknown_speicherort_to_review(tmp_path, monkeypatch):
    result = {
        "ziel_id": "z1",
        "datum": "2026-11-07",
        "absender": "A",
        "dokumenttyp": "B",
        "sicherheit": 0.9,
    }
    ziel = _ziel(id="z1", speicherort="gibt-es-nicht")
    client, data_dir, _ = _client_with_tmp_dirs(
        tmp_path, monkeypatch, result, [ziel]
    )

    response = _upload(client)
    assert response.get_json()["status"] == "zur_pruefung"
    assert (data_dir / "zur-pruefung" / "sample.pdf").exists()


def test_standard_host_pfad_anzeige_wird_bevorzugt(monkeypatch):
    import app.config as config

    monkeypatch.setenv(
        "ARCHIV_HUB_ABLAGE_BASIS_ANZEIGE", "/Volumes/OWC 8TB/data/ablage"
    )
    monkeypatch.setenv("ARCHIV_HUB_STANDARD_HOST_PFAD", "./data/ablage")
    pfad = config.standard_host_pfad()
    assert pfad == "/Volumes/OWC 8TB/data/ablage"
    assert pfad.startswith("/")


def test_standard_host_pfad_faellt_zurueck_ohne_anzeige(monkeypatch):
    import app.config as config

    monkeypatch.delenv("ARCHIV_HUB_ABLAGE_BASIS_ANZEIGE", raising=False)
    monkeypatch.delenv("ARCHIV_HUB_STANDARD_HOST_PFAD", raising=False)
    assert config.standard_host_pfad() == "./data/ablage"


def test_speicherort_skript_erzeugt_yaml_mit_leerzeichen(tmp_path):
    import subprocess

    script_path = (
        Path(__file__).resolve().parent.parent.parent
        / "tools" / "start-stop" / "6-archiv-hub"
        / "66-archiv-hub-speicherort-hinzufuegen.command"
    )
    content = script_path.read_text(encoding="utf-8")
    match = re.search(r"<<'PY'\n(.*?)\nPY", content, re.DOTALL)
    assert match, "Python-Block im Skript 66 nicht gefunden"
    python_code = match.group(1)

    folder = tmp_path / "OWC 8TB" / "archiv"
    folder.mkdir(parents=True)

    env = dict(os.environ)
    env.update({"FOLDER": str(folder), "NAME": "owc", "LABEL": "OWC 8TB"})
    result = subprocess.run(
        [sys.executable, "-c", python_code],
        cwd=str(tmp_path),
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    yaml_text = (tmp_path / "compose.speicherorte.yaml").read_text(encoding="utf-8")
    assert '"%s:/ablage/owc"' % folder in yaml_text

    speicherorte = json.loads(
        (tmp_path / "data" / "speicherorte.json").read_text(encoding="utf-8")
    )
    assert speicherorte == [
        {"name": "owc", "host_pfad": str(folder), "label": "OWC 8TB"}
    ]
    assert speicherorte[0]["host_pfad"].startswith("/")


def test_start_stop_scripts_bash_syntax():
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash nicht verfügbar")

    script_dir = (
        Path(__file__).resolve().parent.parent.parent
        / "tools" / "start-stop" / "6-archiv-hub"
    )
    for name in (
        "60-archiv-hub-A-starten.command",
        "66-archiv-hub-speicherort-hinzufuegen.command",
        "67-archiv-hub-speicherort-entfernen.command",
    ):
        result = subprocess.run(
            [bash, "-n", str(script_dir / name)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{name}: {result.stderr}"


def test_ablage_ordner_listet_unterordner(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    basis = ablage_dir / "standard"
    basis.mkdir(parents=True)
    (basis / "a").mkdir()
    (basis / "b").mkdir()
    (basis / "a" / "unter").mkdir()
    (basis / ".hidden").mkdir()
    (basis / "$RECYCLE.BIN").mkdir()
    (basis / "@eaDir").mkdir()
    (basis / "datei.txt").write_text("kein Ordner")

    r = client.get("/api/ablage/ordner", query_string={"speicherort": "standard"})
    body = r.get_json()
    assert body["ok"] is True
    assert body["ordner"] == ["a", "b"]
    assert body["mehr"] is False


def test_ablage_ordner_legt_ordner_an(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    r = client.post(
        "/api/ablage/ordner",
        json={"speicherort": "standard", "pfad": "", "name": "neu"},
    )
    assert r.get_json()["ok"] is True
    assert (ablage_dir / "standard" / "neu").is_dir()


def test_ablage_ordner_lehnt_ungueltigen_namen_ab(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    for name in ("..", ".hidden", "a/b", "a\\b"):
        r = client.post(
            "/api/ablage/ordner",
            json={"speicherort": "standard", "pfad": "", "name": name},
        )
        assert r.get_json()["ok"] is False, name


def test_ablage_ordner_symlink_ausbruch(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    basis = ablage_dir / "standard"
    basis.mkdir(parents=True)
    outside = tmp_path / "aussen"
    outside.mkdir()
    (basis / "link").symlink_to(outside, target_is_directory=True)

    r = client.get("/api/ablage/ordner", query_string={"speicherort": "standard"})
    assert r.get_json()["ordner"] == []

    r = client.get(
        "/api/ablage/ordner",
        query_string={"speicherort": "standard", "pfad": "link"},
    )
    assert r.get_json()["ok"] is False


def test_ablage_ordner_mehr_als_500(tmp_path, monkeypatch):
    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    basis = ablage_dir / "standard"
    basis.mkdir(parents=True)
    for i in range(510):
        (basis / ("ordner-%03d" % i)).mkdir()

    r = client.get("/api/ablage/ordner", query_string={"speicherort": "standard"})
    body = r.get_json()
    assert body["ok"] is True
    assert len(body["ordner"]) == 500
    assert body["mehr"] is True


# ---------------------------------------------------------------------------
# CSRF-Schutz
# ---------------------------------------------------------------------------


def test_csrf_token_wird_an_die_seite_ausgeliefert(tmp_path, monkeypatch):
    client, _data_dir, _ablage = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    html = client.get("/").get_data(as_text=True)
    assert "ARCHIV_HUB_CSRF" in html


def test_post_ohne_csrf_token_wird_abgewiesen(tmp_path, monkeypatch):
    client, data_dir, _ablage = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    # Token wieder entfernen: der Client sendet dann keinen Header mehr.
    del client.environ_base["HTTP_X_CSRF_TOKEN"]

    r = client.post(
        "/api/ziele", json={"name": "Ohne", "pfad": "ohne"}
    )
    assert r.status_code == 403
    assert r.get_json()["ok"] is False

    # Nichts wurde angelegt.
    assert json.loads((data_dir / "ziele.json").read_text(encoding="utf-8")) == []


def test_post_mit_falschem_csrf_token_wird_abgewiesen(tmp_path, monkeypatch):
    client, data_dir, _ablage = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    client.environ_base["HTTP_X_CSRF_TOKEN"] = "falsches-token"

    r = client.post("/api/ziele", json={"name": "Falsch", "pfad": "falsch"})
    assert r.status_code == 403
    assert json.loads((data_dir / "ziele.json").read_text(encoding="utf-8")) == []


def test_post_mit_gueltigem_csrf_token_ist_erlaubt(tmp_path, monkeypatch):
    client, _data_dir, _ablage = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    r = client.post("/api/ziele", json={"name": "Gültig", "pfad": "gueltig"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True


def test_get_braucht_kein_csrf_token(tmp_path, monkeypatch):
    client, _data_dir, _ablage = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    del client.environ_base["HTTP_X_CSRF_TOKEN"]
    assert client.get("/api/ziele").status_code == 200
    assert client.get("/").status_code == 200


def test_upload_mit_formularfeld_csrf_token(tmp_path, monkeypatch):
    """Multipart-Formulare duerfen das Token auch als Feld senden."""
    client, _data_dir, _ablage = _client_with_tmp_dirs(
        tmp_path, monkeypatch, {"ziel_id": "unklar", "sicherheit": 0.1}, []
    )
    del client.environ_base["HTTP_X_CSRF_TOKEN"]
    r = client.post(
        "/api/upload",
        data={
            "file": (io.BytesIO(_sample_pdf_bytes()), "sample.pdf"),
            "csrf_token": "test-csrf-token",
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Eingangskorb (data/input) – Dateien werden NICHT automatisch verarbeitet
# ---------------------------------------------------------------------------


def _korb_client(tmp_path, monkeypatch, ziele=None):
    """Client mit Eingangskorb; OCR und Klassifizierung sind ersetzt."""
    import app.app as appmod

    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, ziele if ziele is not None else []
    )
    korb = data_dir / "input"
    korb.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(appmod.config, "INPUT_DIR", korb)

    def fake_ocr(src, work):
        aus = work / "out.pdf"
        aus.write_bytes(b"%PDF-1.4 out")
        return aus, "erkannter text"

    monkeypatch.setattr(appmod.ocr, "process", fake_ocr)
    return client, data_dir, korb


def test_korb_listet_nur_unterstuetzte_dateien(tmp_path, monkeypatch):
    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch)
    (korb / "scan.pdf").write_bytes(b"%PDF")
    (korb / "bild.jpg").write_bytes(b"jpg")
    (korb / "notiz.txt").write_text("nein")
    (korb / ".versteckt.pdf").write_bytes(b"%PDF")
    (korb / "unterordner").mkdir()

    r = client.get("/api/korb")
    namen = sorted(f["name"] for f in r.get_json()["dateien"])
    assert namen == ["bild.jpg", "scan.pdf"]


def test_korb_datei_wird_nicht_automatisch_verarbeitet(tmp_path, monkeypatch):
    """Eine Datei im Korb darf ohne Anstoss nichts ausloesen."""
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch)
    (korb / "scan.pdf").write_bytes(b"%PDF")

    assert client.get("/api/korb").get_json()["dateien"]
    # Es wurde nichts verarbeitet: kein Log, keine Kopie im Archiv.
    assert not (data_dir / "archiv.log").exists()
    assert not list((data_dir.parent / "ablage").rglob("*.pdf"))


def test_korb_verarbeiten_legt_ab_und_behaelt_original(tmp_path, monkeypatch):
    """Variante C: Kopie im Ziel, Original wandert nach erledigt/."""
    ziel = _ziel(id="z1", pfad="rechnungen")
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch, [ziel])
    (korb / "scan.pdf").write_bytes(b"%PDF original")

    r = client.post("/api/korb/scan.pdf/verarbeiten", json={"ziel_id": "z1"})
    body = r.get_json()
    assert r.status_code == 200, body
    assert body["status"] == "abgelegt"

    # Original ist nicht mehr im Korb, aber auch nicht geloescht.
    assert not (korb / "scan.pdf").exists()
    assert (korb / "erledigt" / "scan.pdf").read_bytes() == b"%PDF original"

    # Kopie liegt im Zielordner.
    kopien = list((data_dir.parent / "ablage").rglob("*.pdf"))
    assert len(kopien) == 1


def test_korb_verarbeiten_ohne_datei_gibt_404(tmp_path, monkeypatch):
    client, _data_dir, _korb = _korb_client(tmp_path, monkeypatch)
    r = client.post("/api/korb/gibtsnicht.pdf/verarbeiten", json={})
    assert r.status_code == 404


def test_korb_verarbeiten_mit_traversal_wird_abgewiesen(tmp_path, monkeypatch):
    client, _data_dir, _korb = _korb_client(tmp_path, monkeypatch)
    r = client.post("/api/korb/..%2F..%2Fetc%2Fpasswd/verarbeiten", json={})
    assert r.status_code == 404


def test_korb_verarbeiten_mit_inaktivem_ziel_scheitert(tmp_path, monkeypatch):
    ziel = _ziel(id="z1", pfad="rechnungen")
    ziel["aktiv"] = False
    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch, [ziel])
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.post("/api/korb/scan.pdf/verarbeiten", json={"ziel_id": "z1"})
    assert r.status_code == 400
    # Bei einem Fehler bleibt das Original im Korb.
    assert (korb / "scan.pdf").exists()


def test_korb_loeschen_verschiebt_nach_erledigt(tmp_path, monkeypatch):
    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch)
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.delete("/api/korb/scan.pdf")
    assert r.get_json()["ok"] is True
    assert not (korb / "scan.pdf").exists()
    assert (korb / "erledigt" / "scan.pdf").exists()


def test_korb_erledigt_ueberschreibt_nichts(tmp_path, monkeypatch):
    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch)
    for inhalt in (b"erste", b"zweite"):
        (korb / "scan.pdf").write_bytes(inhalt)
        assert client.delete("/api/korb/scan.pdf").get_json()["ok"] is True

    dateien = sorted(p.name for p in (korb / "erledigt").iterdir())
    assert dateien == ["scan (2).pdf", "scan.pdf"]


def test_output_filename_ohne_absender_und_typ():
    """Ohne KI-Angaben entsteht kein Name mit doppelten Trennstrichen."""
    r = pipeline.output_filename(
        {"datum": "2026-11-08", "absender": None, "dokumenttyp": None}, "scan.pdf"
    )
    assert r == "2026-11-08 – scan.pdf"

    r2 = pipeline.output_filename(
        {"datum": "2026-11-08", "absender": None, "dokumenttyp": None}
    )
    assert r2 == "2026-11-08.pdf"


# ---------------------------------------------------------------------------
# Geführter Ablauf: Upload in den Korb und Vorschlag ohne Ablegen
# ---------------------------------------------------------------------------


def test_upload_ablage_legt_nur_in_den_korb(tmp_path, monkeypatch):
    """Hochladen verarbeitet nicht, sondern legt die Datei in den Korb."""
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch)

    r = client.post(
        "/api/upload-ablage",
        data={"file": (io.BytesIO(_sample_pdf_bytes()), "neu.pdf")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["name"] == "neu.pdf"

    assert (korb / "neu.pdf").exists()
    # Nichts wurde verarbeitet.
    assert not (data_dir / "archiv.log").exists()
    assert not list((data_dir.parent / "ablage").rglob("*.pdf"))


def test_upload_ablage_ueberschreibt_nicht(tmp_path, monkeypatch):
    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch)
    for _ in range(2):
        client.post(
            "/api/upload-ablage",
            data={"file": (io.BytesIO(_sample_pdf_bytes()), "gleich.pdf")},
            content_type="multipart/form-data",
        )
    namen = sorted(p.name for p in korb.iterdir() if p.is_file())
    assert namen == ["gleich (2).pdf", "gleich.pdf"]


def test_upload_ablage_weist_falsche_endung_ab(tmp_path, monkeypatch):
    client, _data_dir, _korb = _korb_client(tmp_path, monkeypatch)
    r = client.post(
        "/api/upload-ablage",
        data={"file": (io.BytesIO(b"x"), "boese.exe")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 400


def test_vorschlag_legt_nichts_ab(tmp_path, monkeypatch):
    """Der Vorschlag darf nur analysieren, nie ablegen."""
    ziel = _ziel(id="z1", pfad="rechnungen")
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch, [ziel])
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.post("/api/korb/scan.pdf/vorschlag")
    body = r.get_json()
    assert r.status_code == 200, body
    assert body["ok"] is True

    # Datei ist noch im Korb, nichts im Archiv, kein Log.
    assert (korb / "scan.pdf").exists()
    assert not list((data_dir.parent / "ablage").rglob("*.pdf"))
    assert not (data_dir / "archiv.log").exists()


def test_vorschlag_auch_ohne_ziele(tmp_path, monkeypatch):
    """Ohne angelegte Ziele schlaegt die KI trotzdem einen Ordnernamen vor."""
    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch, [])
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.post("/api/korb/scan.pdf/vorschlag")
    assert r.status_code == 200, r.get_json()
    assert "vorschlag" in r.get_json()


def test_vorschlag_fuer_unbekannte_datei_gibt_404(tmp_path, monkeypatch):
    client, _data_dir, _korb = _korb_client(tmp_path, monkeypatch)
    assert client.post("/api/korb/nix.pdf/vorschlag").status_code == 404


# ---------------------------------------------------------------------------
# Schritt 1: Wege "Scannen" und "Hochladen"
# ---------------------------------------------------------------------------


def test_startseite_zeigt_beide_wege(tmp_path, monkeypatch):
    client, _data_dir, _ablage = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    html = client.get("/").get_data(as_text=True)
    assert "Scannen" in html
    assert "Hochladen" in html
    # Der Skriptname steht hinter der Hilfe, nicht in der Hauptansicht.
    assert "68-archiv-hub-scannen.command" in html
    assert "Digitale Bilder" in html


def test_korb_api_liefert_host_pfad(tmp_path, monkeypatch):
    import app.app as appmod

    client, _data_dir, _korb = _korb_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        appmod.config, "korb_host_pfad", lambda: "/Volumes/OWC 8TB/test/input"
    )
    r = client.get("/api/korb").get_json()
    assert r["host_pfad"] == "/Volumes/OWC 8TB/test/input"


def test_korb_host_pfad_leer_ohne_env(monkeypatch):
    """Ohne Env-Variable bleibt der Host-Pfad leer (kein Finder-Link)."""
    import app.config as config

    monkeypatch.delenv("ARCHIV_HUB_KORB_HOST_PFAD", raising=False)
    assert config.korb_host_pfad() == ""


def test_korb_host_pfad_aus_env(monkeypatch):
    import app.config as config

    monkeypatch.setenv("ARCHIV_HUB_KORB_HOST_PFAD", "/tmp/korb-test")
    assert config.korb_host_pfad() == "/tmp/korb-test"


def test_scannskript_existiert_und_ist_syntaxkorrekt():
    """Skript 68 muss vorhanden und syntaktisch gültig sein."""
    import subprocess

    skript = (
        PROJECT_DIR.parent.parent
        / "tools"
        / "start-stop"
        / "6-archiv-hub"
        / "68-archiv-hub-scannen.command"
    )
    if not skript.is_file():
        pytest.skip("Skript 68 liegt ausserhalb dieses Repositories")
    r = subprocess.run(["bash", "-n", str(skript)], capture_output=True)
    assert r.returncode == 0, r.stderr.decode()


def test_scannskript_oeffnet_digitale_bilder():
    skript = (
        PROJECT_DIR.parent.parent
        / "tools"
        / "start-stop"
        / "6-archiv-hub"
        / "68-archiv-hub-scannen.command"
    )
    if not skript.is_file():
        pytest.skip("Skript 68 liegt ausserhalb dieses Repositories")
    inhalt = skript.read_text(encoding="utf-8")
    assert "Image Capture" in inhalt
    assert "data/input" in inhalt


# ---------------------------------------------------------------------------
# Sichtbarkeit: das hidden-Attribut muss greifen
# ---------------------------------------------------------------------------


def test_css_erzwingt_hidden():
    """Ohne [hidden]{display:none} bleiben Buttons mit display:inline-flex
    trotz hidden sichtbar – genau dieser Fehler ist schon einmal aufgetreten."""
    css = (PROJECT_DIR / "app" / "static" / "archiv.css").read_text(encoding="utf-8")
    assert re.search(r"\[hidden\]\s*\{[^}]*display:\s*none", css), (
        "CSS muss [hidden] { display: none !important; } enthalten"
    )


# ---------------------------------------------------------------------------
# Ziele: Wurzelordner und klare Fehlermeldungen
# ---------------------------------------------------------------------------


def test_ziel_ohne_pfad_ist_erlaubt(tmp_path, monkeypatch):
    """Ein leerer Pfad bedeutet: direkt im Wurzelordner des Speicherorts."""
    client, _data_dir, _ablage = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    r = client.post("/api/ziele", json={"name": "Direkt", "speicherort": "standard"})
    assert r.status_code == 200, r.get_json()
    # Ohne Pfad wird kein pfad-Feld gesetzt; gelesen wird es als leerer String.
    assert not r.get_json()["ziel"].get("pfad")


def test_ziel_ohne_namen_wird_abgelehnt(tmp_path, monkeypatch):
    client, _data_dir, _ablage = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    r = client.post("/api/ziele", json={"pfad": "irgendwas"})
    assert r.status_code == 400
    assert "Name" in r.get_json()["error"]


def test_ziel_mit_unbekanntem_speicherort_nennt_den_namen(tmp_path, monkeypatch):
    client, _data_dir, _ablage = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    r = client.post(
        "/api/ziele", json={"name": "X", "speicherort": "gibtsnicht"}
    )
    assert r.status_code == 400
    assert "gibtsnicht" in r.get_json()["error"]


def test_ziel_im_wurzelordner_legt_dort_ab(tmp_path, monkeypatch):
    """Ein Ziel ohne Pfad legt Dokumente direkt im Speicherort ab."""
    import app.app as appmod

    client, data_dir, ablage_dir = _client_with_tmp_dirs(
        tmp_path, monkeypatch, None, []
    )
    monkeypatch.setattr(appmod.config, "INPUT_DIR", data_dir / "input")
    (data_dir / "input").mkdir(parents=True, exist_ok=True)

    def fake_ocr(src, work):
        aus = work / "out.pdf"
        aus.write_bytes(b"%PDF")
        return aus, "text"

    monkeypatch.setattr(appmod.ocr, "process", fake_ocr)

    r = client.post("/api/ziele", json={"name": "Direkt", "speicherort": "standard"})
    ziel_id = r.get_json()["ziel"]["id"]

    (data_dir / "input" / "s.pdf").write_bytes(b"%PDF")
    r2 = client.post("/api/korb/s.pdf/verarbeiten", json={"ziel_id": ziel_id})
    assert r2.status_code == 200, r2.get_json()
    # Die Datei liegt direkt unter /ablage/standard, nicht in einem Unterordner.
    treffer = list((ablage_dir / "standard").glob("*.pdf"))
    assert treffer, "Datei nicht im Wurzelordner abgelegt"


# ---------------------------------------------------------------------------
# Direktes Ablegen in einen Ordner (ohne vorher ein Ziel anzulegen)
# ---------------------------------------------------------------------------


def test_direkt_ablegen_ohne_ziel(tmp_path, monkeypatch):
    """Der Kern der Vereinfachung: Ordner wählen, ablegen - ohne Ziel-Umweg."""
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch, [])
    (korb / "scan.pdf").write_bytes(b"%PDF original")

    r = client.post(
        "/api/korb/scan.pdf/ablegen",
        json={"speicherort": "standard", "pfad": ""},
    )
    body = r.get_json()
    assert r.status_code == 200, body
    assert body["status"] == "abgelegt"

    # Im Wurzelordner des Speicherorts liegt jetzt ein PDF.
    treffer = list((data_dir.parent / "ablage" / "standard").glob("*.pdf"))
    assert len(treffer) == 1
    # Und das Original ist nicht gelöscht.
    assert (korb / "erledigt" / "scan.pdf").exists()


def test_direkt_ablegen_in_unterordner(tmp_path, monkeypatch):
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch, [])
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.post(
        "/api/korb/scan.pdf/ablegen",
        json={"speicherort": "standard", "pfad": "Rechnungen"},
    )
    assert r.status_code == 200, r.get_json()
    treffer = list((data_dir.parent / "ablage" / "standard" / "Rechnungen").glob("*.pdf"))
    assert len(treffer) == 1


def test_direkt_ablegen_legt_neuen_unterordner_an(tmp_path, monkeypatch):
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch, [])
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.post(
        "/api/korb/scan.pdf/ablegen",
        json={"speicherort": "standard", "pfad": "", "unterordner": "Neu"},
    )
    assert r.status_code == 200, r.get_json()
    assert (data_dir.parent / "ablage" / "standard" / "Neu").is_dir()


def test_direkt_ablegen_weist_traversal_ab(tmp_path, monkeypatch):
    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch, [])
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.post(
        "/api/korb/scan.pdf/ablegen",
        json={"speicherort": "standard", "pfad": "../../etc"},
    )
    assert r.status_code == 400


def test_ordner_liste_liefert_alle_speicherorte(tmp_path, monkeypatch):
    client, _data_dir, _korb = _korb_client(tmp_path, monkeypatch)
    r = client.get("/api/ablage/ordner-liste")
    body = r.get_json()
    assert body["ok"] is True
    assert any(s["speicherort"] == "standard" for s in body["speicherorte"])
    eintrag = [s for s in body["speicherorte"] if s["speicherort"] == "standard"][0]
    assert "host_pfad" in eintrag
    assert isinstance(eintrag["ordner"], list)


# ---------------------------------------------------------------------------
# Dateiname: KI-Vorschlag, vom Nutzer überschreibbar
# ---------------------------------------------------------------------------


def test_safe_filename_bereinigt_pfadangaben():
    """Ein eingegebener Name darf keine Pfadanteile enthalten."""
    assert pipeline.safe_filename("../../etc/passwd") == "passwd.pdf"
    assert pipeline.safe_filename("unter/ordner/datei.pdf") == "datei.pdf"
    assert pipeline.safe_filename("a\\b\\c.pdf") == "c.pdf"


def test_safe_filename_entfernt_verbotene_zeichen():
    assert pipeline.safe_filename('Rechnung: "Muster" <2026>.pdf') == "Rechnung Muster 2026.pdf"
    assert pipeline.safe_filename("Test|Name?.pdf") == "TestName.pdf"


def test_safe_filename_setzt_pdf_endung():
    assert pipeline.safe_filename("Rechnung") == "Rechnung.pdf"
    assert pipeline.safe_filename("Rechnung.pdf") == "Rechnung.pdf"
    assert pipeline.safe_filename("Bild.jpg") == "Bild.pdf"


def test_safe_filename_fallback_bei_leerem_namen():
    assert pipeline.safe_filename("") == "Dokument.pdf"
    assert pipeline.safe_filename("   ") == "Dokument.pdf"
    assert pipeline.safe_filename("...") == "Dokument.pdf"


def test_safe_filename_kuerzt_lange_namen():
    lang = "A" * 500
    assert len(pipeline.safe_filename(lang)) <= 200


def test_ablegen_mit_eigenem_dateinamen(tmp_path, monkeypatch):
    """Der vom Nutzer vorgegebene Dateiname wird verwendet."""
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch, [])
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.post(
        "/api/korb/scan.pdf/ablegen",
        json={
            "speicherort": "standard",
            "pfad": "",
            "dateiname": "2026-11-08 – Muster AG – Rechnung.pdf",
        },
    )
    assert r.status_code == 200, r.get_json()
    treffer = list((data_dir.parent / "ablage" / "standard").glob("*.pdf"))
    assert len(treffer) == 1
    assert treffer[0].name == "2026-11-08 – Muster AG – Rechnung.pdf"


def test_ablegen_ohne_dateiname_baut_standardnamen(tmp_path, monkeypatch):
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch, [])
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.post(
        "/api/korb/scan.pdf/ablegen",
        json={"speicherort": "standard", "pfad": ""},
    )
    assert r.status_code == 200, r.get_json()
    treffer = list((data_dir.parent / "ablage" / "standard").glob("*.pdf"))
    assert treffer[0].name.startswith("20")  # Datum am Anfang
    assert treffer[0].name.endswith(".pdf")


def test_ablegen_mit_boesem_dateinamen_wird_entschaerft(tmp_path, monkeypatch):
    """Ein Dateiname mit Pfadanteil darf nicht aus dem Ordner ausbrechen."""
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch, [])
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.post(
        "/api/korb/scan.pdf/ablegen",
        json={
            "speicherort": "standard",
            "pfad": "",
            "dateiname": "../../../ausserhalb.pdf",
        },
    )
    assert r.status_code == 200, r.get_json()
    # Die Datei liegt im Zielordner, nicht ausserhalb.
    treffer = list((data_dir.parent / "ablage" / "standard").glob("*.pdf"))
    assert len(treffer) == 1
    assert treffer[0].name == "ausserhalb.pdf"


def test_vorschlag_liefert_dateiname_und_pfad(tmp_path, monkeypatch):
    """Der Vorschlag enthaelt Dateiname und Ordnerpfad zum Vorbelegen."""
    ziel = _ziel(id="z1", pfad="rechnungen")
    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch, [ziel])
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.post("/api/korb/scan.pdf/vorschlag")
    body = r.get_json()
    assert r.status_code == 200, body
    if body.get("vorschlag"):
        assert "dateiname" in body["vorschlag"]
        assert "ordner" in body["vorschlag"]
        assert "speicherort" in body["vorschlag"]
        assert "ordner_vorhanden" in body["vorschlag"]


# ---------------------------------------------------------------------------
# Direktscan über eSCL (ohne echtes Gerät: XML und Validierung)
# ---------------------------------------------------------------------------


def test_escl_xml_flachbett():
    from app import scanner_escl as es

    xml = es._scan_einstellungen("flachbett", 300, "farbe")
    assert "<pwg:InputSource>Platen</pwg:InputSource>" in xml
    assert "<scan:XResolution>300</scan:XResolution>" in xml
    assert "<scan:ColorMode>RGB24</scan:ColorMode>" in xml
    assert "application/pdf" in xml


def test_escl_xml_einzug_duplex():
    from app import scanner_escl as es

    xml = es._scan_einstellungen("einzug", 200, "grau", duplex=True)
    assert "<pwg:InputSource>Feeder</pwg:InputSource>" in xml
    assert "<scan:Duplex>true</scan:Duplex>" in xml
    assert "Grayscale8" in xml
    assert "200" in xml


def test_escl_xml_sw_modus():
    from app import scanner_escl as es

    xml = es._scan_einstellungen("flachbett", 600, "sw")
    assert "BlackAndWhite1" in xml
    assert "600" in xml


def test_escl_lehnt_unbekannte_werte_ab():
    from app import scanner_escl as es

    for args in (
        ("gibtsnicht", 300, "farbe"),
        ("flachbett", 999, "farbe"),
        ("flachbett", 300, "gibtsnicht"),
    ):
        with pytest.raises(es.ScannerFehler):
            es._scan_einstellungen(*args)


def test_escl_braucht_url():
    from app import scanner_escl as es

    with pytest.raises(es.ScannerFehler):
        es.status("")
    with pytest.raises(es.ScannerFehler):
        es.status("   ")


def test_escl_basis_url_ergaenzt_schema():
    from app import scanner_escl as es

    assert es._basis_url("192.168.1.5") == "http://192.168.1.5"
    assert es._basis_url("http://192.168.1.5/") == "http://192.168.1.5"


def test_scanner_status_ohne_konfiguration(tmp_path, monkeypatch):
    """Ohne ARCHIV_HUB_SCANNER_URL meldet der Hub: nicht eingerichtet."""
    import app.app as appmod

    client, _data_dir, _korb = _korb_client(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod.config, "scanner_url", lambda: "")
    r = client.get("/api/scanner/status").get_json()
    assert r["konfiguriert"] is False
    assert r["bereit"] is False


def test_scanner_scan_ohne_konfiguration(tmp_path, monkeypatch):
    import app.app as appmod

    client, _data_dir, _korb = _korb_client(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod.config, "scanner_url", lambda: "")
    r = client.post("/api/scanner/scan", json={"quelle": "flachbett"})
    assert r.status_code == 400


def test_scanner_scan_legt_datei_im_korb(tmp_path, monkeypatch):
    """Ein erfolgreicher Scan landet als PDF im Eingangskorb."""
    import app.app as appmod
    from app import scanner_escl as es

    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod.config, "scanner_url", lambda: "http://test")

    def fake_scan(url, quelle, aufloesung, farbmodus, duplex, format_):
        return b"%PDF-1.4 gescannt", "application/pdf"

    monkeypatch.setattr(es, "scanne", fake_scan)

    r = client.post(
        "/api/scanner/scan",
        json={"quelle": "flachbett", "aufloesung": 300, "farbmodus": "farbe"},
    )
    body = r.get_json()
    assert r.status_code == 200, body
    assert body["name"].startswith("Scan_")
    assert body["name"].endswith(".pdf")
    assert (korb / body["name"]).read_bytes().startswith(b"%PDF")


def test_scanner_scan_meldet_geraetefehler(tmp_path, monkeypatch):
    import app.app as appmod
    from app import scanner_escl as es

    client, _data_dir, _korb = _korb_client(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod.config, "scanner_url", lambda: "http://test")

    def fake_scan(*a, **k):
        raise es.ScannerFehler("Gerät beschäftigt")

    monkeypatch.setattr(es, "scanne", fake_scan)
    r = client.post("/api/scanner/scan", json={})
    assert r.status_code == 502
    assert "beschäftigt" in r.get_json()["error"]


# ---------------------------------------------------------------------------
# Zeitzone: Datumsangaben müssen lokale Zeit sein, nicht UTC
# ---------------------------------------------------------------------------


def test_config_liefert_lokale_zeit():
    """Im Container läuft die Uhr in UTC – config.jetzt() muss das ausgleichen."""
    import app.config as config

    jetzt = config.jetzt()
    assert jetzt.tzinfo is not None, "jetzt() muss zeitzonenbewusst sein"
    # Europe/Zurich liegt im Winter bei +01:00, im Sommer bei +02:00.
    offset = jetzt.utcoffset()
    assert offset is not None
    assert offset.total_seconds() in (3600, 7200), f"Unerwarteter Offset: {offset}"


def test_scan_dateiname_nutzt_lokale_zeit(tmp_path, monkeypatch):
    """Der Zeitstempel im Scan-Dateinamen kommt aus config.jetzt()."""
    import app.app as appmod
    from app import scanner_escl as es

    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod.config, "scanner_url", lambda: "http://test")
    monkeypatch.setattr(
        es, "scanne", lambda *a, **k: (b"%PDF-1.4 x", "application/pdf")
    )

    r = client.post("/api/scanner/scan", json={})
    name = r.get_json()["name"]
    erwartet = appmod.config.jetzt().strftime("%Y-%m-%d_%H")
    assert erwartet in name, f"Lokale Zeit fehlt im Namen: {name}"


def test_ordner_liste_blendet_standard_aus(tmp_path, monkeypatch):
    """Sobald ein echter Speicherort existiert, wird der Testordner
    'standard' nicht mehr angeboten."""
    import app.app as appmod
    import app.storage as storage

    client, _data_dir, _korb = _korb_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        storage,
        "locations",
        lambda: [
            {"name": "standard", "host_pfad": "/tmp/ablage", "label": "Standard"},
            {"name": "archiv", "host_pfad": "/tmp/archiv", "label": "Archiv"},
        ],
    )
    monkeypatch.setattr(storage, "list_folders", lambda s, p: ([], False))

    r = client.get("/api/ablage/ordner-liste").get_json()
    namen = [s["speicherort"] for s in r["speicherorte"]]
    assert namen == ["archiv"], f"standard haette ausgeblendet sein muessen: {namen}"


def test_ordner_liste_zeigt_standard_wenn_allein(tmp_path, monkeypatch):
    """Ohne echten Speicherort bleibt 'standard' sichtbar."""
    import app.storage as storage

    client, _data_dir, _korb = _korb_client(tmp_path, monkeypatch)
    monkeypatch.setattr(
        storage,
        "locations",
        lambda: [
            {"name": "standard", "host_pfad": "/tmp/ablage", "label": "Standard"}
        ],
    )
    monkeypatch.setattr(storage, "list_folders", lambda s, p: ([], False))

    r = client.get("/api/ablage/ordner-liste").get_json()
    assert [s["speicherort"] for s in r["speicherorte"]] == ["standard"]


# ---------------------------------------------------------------------------
# Neue Ordner dürfen vorgeschlagen und angelegt werden
# ---------------------------------------------------------------------------


def test_safe_ordnername_bereinigt():
    for boese, erwartet in (
        ("../../etc", "etc"),
        ("A/B", "B"),
        ("Test.pdf", "Test"),
        ("", "Sonstiges"),
        ("   ", "Sonstiges"),
        ("Arzt: Bericht", "Arzt Bericht"),
    ):
        assert pipeline.safe_ordnername(boese) == erwartet, boese
    assert pipeline.safe_ordnername("Übungen") == "Übungen"


def test_ablegen_legt_neuen_ordner_an(tmp_path, monkeypatch):
    """Ein vorgeschlagener Ordnername, den es noch nicht gibt, wird angelegt."""
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch, [])
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.post(
        "/api/korb/scan.pdf/ablegen",
        json={
            "speicherort": "standard",
            "pfad": "Uebungsanleitungen",
            "dateiname": "2026-11-08 – Uebungsanleitung.pdf",
        },
    )
    assert r.status_code == 200, r.get_json()
    ordner = data_dir.parent / "ablage" / "standard" / "Uebungsanleitungen"
    assert ordner.is_dir(), "Ordner wurde nicht angelegt"
    assert list(ordner.glob("*.pdf"))


def test_ablegen_verhindert_ordner_traversal(tmp_path, monkeypatch):
    """Ein Ordnername mit Pfadanteil darf nicht aus dem Archiv ausbrechen."""
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch, [])
    (korb / "scan.pdf").write_bytes(b"%PDF")

    r = client.post(
        "/api/korb/scan.pdf/ablegen",
        json={"speicherort": "standard", "pfad": "../../ausserhalb"},
    )
    assert r.status_code in (200, 400), r.get_json()
    if r.status_code == 200:
        # Nichts darf ausserhalb des Ablageordners entstanden sein.
        assert not (data_dir.parent / "ausserhalb").exists()


def test_dateiname_nutzt_dokumentdatum():
    """Das Datum aus dem Dokument hat Vorrang vor dem Scandatum."""
    r = pipeline.output_filename(
        {"datum": "2026-10-15", "dokumentname": "Serverwartung",
         "dokumenttyp": "Rechnung"},
        fallback_datum="2026-11-08",
        ordner="Rechnungen",
    )
    assert r == "2026-10-15 – Rechnungen – Serverwartung.pdf"


def test_dateiname_faellt_auf_scandatum_zurueck():
    """Ohne Datum im Dokument wird das Scandatum verwendet."""
    r = pipeline.output_filename(
        {"datum": "", "dokumentname": "Ischias", "dokumenttyp": "Uebungsanleitung"},
        fallback_datum="2026-11-08",
        ordner="Uebungsanleitungen",
    )
    assert r == "2026-11-08 – Uebungsanleitungen – Ischias.pdf"


def test_dateiname_ohne_platzhalter():
    """Leere Teile werden weggelassen – kein 'Unbekannt'."""
    r = pipeline.output_filename(
        {"datum": "2026-11-08", "dokumentname": "", "dokumenttyp": "Uebungsanleitung"},
        ordner="Uebungsanleitungen",
    )
    assert r == "2026-11-08 – Uebungsanleitungen – Uebungsanleitung.pdf"
    assert "Unbekannt" not in r


def test_dateiname_verdoppelt_kein_datum():
    """Steht im Originalnamen schon ein Datum, wird keines vorangestellt."""
    r = pipeline.output_filename(
        {"datum": "2026-11-08", "absender": "", "dokumenttyp": ""},
        original_name="Scan_2026-11-08_14-01-32.pdf",
        fallback_datum="2026-11-08",
    )
    assert r == "Scan_2026-11-08_14-01-32.pdf"


# ---------------------------------------------------------------------------
# Dateiformate beim Scannen und Ablegen
# ---------------------------------------------------------------------------


def _jpeg_bytes():
    import io as _io

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (40, 20), (200, 200, 200)).save(buf, format="JPEG")
    return buf.getvalue()


def test_scan_format_pdf_ergibt_pdf(tmp_path, monkeypatch):
    import app.app as appmod
    from app import scanner_escl as es

    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod.config, "scanner_url", lambda: "http://test")
    monkeypatch.setattr(
        es, "scanne", lambda *a, **k: (b"%PDF-1.4 x", "application/pdf")
    )

    r = client.post("/api/scanner/scan", json={"format": "pdf"})
    name = r.get_json()["name"]
    assert name.endswith(".pdf")
    assert (korb / name).read_bytes().startswith(b"%PDF")


def test_scan_format_jpeg_ergibt_jpg(tmp_path, monkeypatch):
    import app.app as appmod
    from app import scanner_escl as es

    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod.config, "scanner_url", lambda: "http://test")
    monkeypatch.setattr(
        es, "scanne", lambda *a, **k: (_jpeg_bytes(), "image/jpeg")
    )

    r = client.post("/api/scanner/scan", json={"format": "jpeg"})
    name = r.get_json()["name"]
    assert name.endswith(".jpg"), name
    assert (korb / name).read_bytes().startswith(b"\xff\xd8")


def test_scan_format_png_wandelt_um(tmp_path, monkeypatch):
    """Der Scanner kann kein PNG – der Hub wandelt das JPEG um."""
    import app.app as appmod
    from app import scanner_escl as es

    client, _data_dir, korb = _korb_client(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod.config, "scanner_url", lambda: "http://test")

    aufgerufen = {}

    def fake_scan(url, quelle, aufloesung, farbmodus, duplex, format_):
        aufgerufen["format"] = format_
        return _jpeg_bytes(), "image/jpeg"

    monkeypatch.setattr(es, "scanne", fake_scan, raising=False)
    monkeypatch.setattr(es, "scanne", fake_scan)

    r = client.post("/api/scanner/scan", json={"format": "png"})
    name = r.get_json()["name"]
    assert name.endswith(".png"), name
    # Der Scanner wurde mit JPEG beauftragt, nicht mit PNG.
    assert aufgerufen.get("format") == "jpeg"
    assert (korb / name).read_bytes().startswith(b"\x89PNG")


def test_scan_lehnt_unbekanntes_format_ab(tmp_path, monkeypatch):
    import app.app as appmod

    client, _data_dir, _korb = _korb_client(tmp_path, monkeypatch)
    monkeypatch.setattr(appmod.config, "scanner_url", lambda: "http://test")
    r = client.post("/api/scanner/scan", json={"format": "docx"})
    assert r.status_code == 400


def test_bild_bleibt_beim_ablegen_bild(tmp_path, monkeypatch):
    """Ein JPEG im Korb wird als JPEG abgelegt, nicht in PDF umgewandelt."""
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch, [])
    (korb / "scan.jpg").write_bytes(_jpeg_bytes())

    r = client.post(
        "/api/korb/scan.jpg/ablegen",
        json={
            "speicherort": "standard",
            "pfad": "Bilder",
            "dateiname": "2026-11-08 – Foto.jpg",
        },
    )
    assert r.status_code == 200, r.get_json()
    treffer = list((data_dir.parent / "ablage" / "standard" / "Bilder").glob("*"))
    assert len(treffer) == 1
    assert treffer[0].suffix == ".jpg", treffer[0].name
    assert treffer[0].read_bytes().startswith(b"\xff\xd8")


def test_pdf_wird_beim_ablegen_pdf(tmp_path, monkeypatch):
    client, data_dir, korb = _korb_client(tmp_path, monkeypatch, [])
    (korb / "scan.pdf").write_bytes(b"%PDF-1.4 original")

    r = client.post(
        "/api/korb/scan.pdf/ablegen",
        json={"speicherort": "standard", "pfad": "", "dateiname": "Dokument.pdf"},
    )
    assert r.status_code == 200, r.get_json()
    treffer = list((data_dir.parent / "ablage" / "standard").glob("*.pdf"))
    assert treffer and treffer[0].read_bytes().startswith(b"%PDF")


def test_safe_filename_behaelt_gewuenschte_endung():
    assert pipeline.safe_filename("Bild", endung=".jpg") == "Bild.jpg"
    assert pipeline.safe_filename("Bild.png", endung=".jpg") == "Bild.jpg"
    assert pipeline.safe_filename("Bild", endung=".png") == "Bild.png"
    # Standard bleibt PDF.
    assert pipeline.safe_filename("Bild") == "Bild.pdf"


# ---------------------------------------------------------------------------
# Umlaute in Ordnernamen und Dateinamen
# ---------------------------------------------------------------------------


def test_ordnername_behaelt_umlaute():
    """ä, ö, ü und ß dürfen nicht verstümmelt werden."""
    for name in ("Übungsanleitungen", "Prämien", "Ärzte", "Größe", "Straße"):
        assert pipeline.safe_ordnername(name) == name


def test_dateiname_behaelt_umlaute():
    name = pipeline.safe_filename("2026-11-08 – Übungsanleitungen – Prämien.pdf")
    assert name == "2026-11-08 – Übungsanleitungen – Prämien.pdf"


def test_umlaut_und_umschreibung_gelten_als_gleich():
    """Für die Doppelungs-Prüfung sind Ü/UE gleich."""
    r = pipeline.output_filename(
        {"datum": "2026-11-08", "dokumentname": "Übungsanleitungen",
         "dokumenttyp": "X"},
        ordner="Uebungsanleitungen",
    )
    # Nicht doppelt nennen – die Schreibweise des Dokuments gewinnt.
    assert r == "2026-11-08 – Übungsanleitungen.pdf"


# ---------------------------------------------------------------------------
# JavaScript: aufgerufene Funktionen müssen auch definiert sein
# ---------------------------------------------------------------------------


def test_js_ruft_nur_definierte_funktionen_auf():
    """Findet Tippfehler und versehentlich gelöschte Funktionen.

    Hintergrund: Ein fehlender Funktionsname führt im Browser zu einem
    ReferenceError, der die restliche Ausführung einer Funktion abbricht –
    das bleibt bei Python-Tests unbemerkt.
    """
    js = (PROJECT_DIR / "app" / "static" / "index.js").read_text(encoding="utf-8")

    definiert = set(re.findall(r"function\s+(\w+)", js))
    definiert |= set(re.findall(r"var\s+(\w+)\s*=", js))
    definiert |= set(re.findall(r"(\w+)\s*=\s*function", js))

    # Eigene Aufrufe: Wort mit Klammer, das wie eine Projektfunktion aussieht.
    eigen = re.findall(r"\b((?:zeige|leere|setze|lade|starte|stoppe|pruefe|"
                       r"scan|korb|neuen|aktu|ziel|ausfuehr|vorschlag|"
                       r"ordner|wahl|speicherort)\w*)\s*\(", js)

    fehlend = sorted(set(eigen) - definiert)
    assert not fehlend, f"Nicht definierte Funktionen aufgerufen: {fehlend}"


def test_js_blendet_schritte_nach_dem_ablegen_nicht_aus():
    """Die Schritte 4 und 5 müssen sichtbar bleiben (Anforderung des Nutzers)."""
    js = (PROJECT_DIR / "app" / "static" / "index.js").read_text(encoding="utf-8")

    # Beim Ablegen darf nicht ausgeblendet werden.
    stelle = js.index('"/ablegen", "POST"')
    umgebung = js[stelle:stelle + 900]
    assert "zeigeArbeitsbereiche(false" not in umgebung, (
        "Nach dem Ablegen dürfen die Bereiche nicht ausgeblendet werden"
    )


def test_js_graut_ablegen_nach_dem_ablegen_aus():
    """Nach dem Ablegen wird der Knopf inaktiv; 'Zurück' macht ihn wieder aktiv."""
    js = (PROJECT_DIR / "app" / "static" / "index.js").read_text(encoding="utf-8")

    # Der Merker existiert und wird gesetzt bzw. zurückgesetzt.
    assert "bereitsAbgelegt" in js
    assert "bereitsAbgelegt = true" in js, "Merker wird nach dem Ablegen nicht gesetzt"
    assert "bereitsAbgelegt = false" in js, "Merker wird nicht zurückgesetzt"

    # Der Knopfzustand berücksichtigt den Merker.
    assert "ablageOffen && !bereitsAbgelegt" in js, (
        "Der Ablegen-Knopf berücksichtigt den Merker nicht"
    )

    # Der Zurück-Knopf setzt den Merker zurück.
    stelle = js.index('document.getElementById("btn-zurueck")')
    umgebung = js[stelle:stelle + 500]
    assert "bereitsAbgelegt = false" in umgebung, (
        "Zurück setzt den Merker nicht zurück"
    )


def test_js_hat_neue_quelle_knopf():
    """Nach dem Ablegen führt ein Knopf zurück zum Anfang."""
    js = (PROJECT_DIR / "app" / "static" / "index.js").read_text(encoding="utf-8")
    html = (PROJECT_DIR / "app" / "templates" / "index.html").read_text(encoding="utf-8")

    assert 'id="btn-neue-quelle"' in html, "Knopf fehlt im Template"
    assert "btn-neue-quelle" in js, "Knopf hat keinen Handler"
    assert 'id="zeile-neu"' in html, "Zeile für den Knopf fehlt"

    # Nach dem Ablegen wird der Knopf eingeblendet.
    stelle = js.index('"/ablegen", "POST"')
    umgebung = js[stelle:stelle + 900]
    assert 'zeile-neu").hidden = false' in umgebung, (
        "Der Knopf wird nach dem Ablegen nicht eingeblendet"
    )

    # Beim Klick wird zurückgesetzt.
    stelle2 = js.index('"btn-neue-quelle"')
    umgebung2 = js[stelle2:stelle2 + 900]
    assert "zeigeSchritt(1)" in umgebung2, "Zurücksetzen fehlt"
    assert "bereitsAbgelegt = false" in umgebung2, "Merker wird nicht gelöscht"


def test_escl_einzug_hat_feeder_anweisung():
    """Beim Einzug wird <pwg:InputSource>Feeder</pwg:InputSource> gesendet.

    Vorbild ist sane-airscan (airscan-escl.c): dort heisst die Quelle beim
    Einzug "Feeder" – nicht "AdfSimplex". Duplex wird separat über
    scan:Duplex mitgeteilt.
    """
    from app import scanner_escl as es

    xml_einzug = es._scan_einstellungen("einzug", 300, "farbe")
    assert "<pwg:InputSource>Feeder</pwg:InputSource>" in xml_einzug
    assert "<scan:Duplex>false</scan:Duplex>" in xml_einzug
    assert "scan:InputSource" not in xml_einzug

    xml_duplex = es._scan_einstellungen("einzug", 300, "farbe", duplex=True)
    assert "<pwg:InputSource>Feeder</pwg:InputSource>" in xml_duplex
    assert "<scan:Duplex>true</scan:Duplex>" in xml_duplex

    # Beim Flachbett gibt es keinen Einzug und kein Duplex.
    xml_flach = es._scan_einstellungen("flachbett", 300, "farbe")
    assert "Feeder" not in xml_flach
    assert "Duplex" not in xml_flach
    assert "<pwg:InputSource>Platen</pwg:InputSource>" in xml_flach


def test_escl_quelle_ist_korrekt():
    from app import scanner_escl as es

    einzug = es._scan_einstellungen("einzug", 300, "farbe")
    assert "<pwg:InputSource>Feeder</pwg:InputSource>" in einzug
    duplex = es._scan_einstellungen("einzug", 300, "farbe", duplex=True)
    assert "<scan:Duplex>true</scan:Duplex>" in duplex
    flach = es._scan_einstellungen("flachbett", 300, "farbe")
    assert "<pwg:InputSource>Platen</pwg:InputSource>" in flach


def test_escl_region_in_dreihundertstel_zoll():
    """Die Region ist immer in 1/300 Zoll – unabhängig von der Auflösung."""
    from app import scanner_escl as es

    for dpi in (100, 200, 300, 600):
        xml = es._scan_einstellungen("einzug", dpi, "farbe")
        assert f"<pwg:Width>{es.REGION_BREITE}</pwg:Width>" in xml
        assert f"<pwg:Height>{es.REGION_HOEHE}</pwg:Height>" in xml


# ---------------------------------------------------------------------------
# Einzug: alle Seiten abholen und zu einem PDF zusammenführen
# ---------------------------------------------------------------------------


def _ein_seiten_pdf():
    import io as _io

    from pypdf import PdfWriter

    w = PdfWriter()
    w.add_blank_page(width=595, height=842)
    b = _io.BytesIO()
    w.write(b)
    return b.getvalue()


def test_escl_fuehrt_seiten_zusammen():
    """Mehrere Ein-Seiten-PDFs ergeben ein PDF mit allen Seiten."""
    import io as _io

    from app import scanner_escl as es
    from pypdf import PdfReader

    seiten = [_ein_seiten_pdf() for _ in range(3)]
    ergebnis = es._seiten_zusammenfuehren(seiten)

    assert ergebnis.startswith(b"%PDF")
    assert len(PdfReader(_io.BytesIO(ergebnis)).pages) == 3


def test_escl_alle_seiten_holt_bis_zum_ende():
    """_alle_seiten ruft so lange ab, bis der Scanner nichts mehr liefert."""
    from app import scanner_escl as es

    aufrufe = {"n": 0}

    def fake_hole(url, timeout):
        aufrufe["n"] += 1
        if aufrufe["n"] <= 3:
            return 200, _ein_seiten_pdf()
        raise es.ScannerFehler("keine weitere Seite")

    alt_hole, alt_offen = es._hole, es._seiten_offen
    es._hole = fake_hole
    es._seiten_offen = lambda url: False   # Auftrag ist beendet
    try:
        seiten = es._alle_seiten("http://test/job/NextDocument")
    finally:
        es._hole, es._seiten_offen = alt_hole, alt_offen

    assert len(seiten) == 3, f"Erwartet 3 Seiten, bekam {len(seiten)}"


def test_escl_alle_seiten_wiederholt_bei_offenem_auftrag():
    """Bei offenem Auftrag wird ein Fehlversuch wiederholt (Brother-Eigenheit).

    Der Brother MFC-L2980DW liefert zwischen zwei Seiten sporadisch HTTP 404,
    obwohl noch Seiten im Einzug liegen. Der Abruf muss dann wiederholt
    werden, statt den Auftrag abzubrechen.
    """
    from app import scanner_escl as es

    aufrufe = {"n": 0}

    def fake_hole(url, timeout):
        aufrufe["n"] += 1
        # Seite 1, dann zwei Fehlversuche, dann Seite 2, dann Ende.
        if aufrufe["n"] == 1:
            return 200, _ein_seiten_pdf()
        if aufrufe["n"] in (2, 3):
            raise es.ScannerFehler("HTTP 404")
        if aufrufe["n"] == 4:
            return 200, _ein_seiten_pdf()
        raise es.ScannerFehler("HTTP 404")

    # Auftrag gilt als offen, solange weniger als 4 Aufrufe erfolgt sind.
    def fake_offen(url):
        return aufrufe["n"] < 4

    alt_hole, alt_offen = es._hole, es._seiten_offen
    es._hole = fake_hole
    es._seiten_offen = fake_offen
    try:
        seiten = es._alle_seiten("http://test/job/NextDocument")
    finally:
        es._hole, es._seiten_offen = alt_hole, alt_offen

    assert len(seiten) == 2, f"Erwartet 2 Seiten trotz Fehlversuchen, bekam {len(seiten)}"


def test_escl_alle_seiten_begrenzt_die_anzahl():
    """Die Schleife läuft nicht endlos, wenn der Scanner immer liefert."""
    from app import scanner_escl as es

    def fake_hole(url, timeout):
        return 200, _ein_seiten_pdf()

    alt = es._hole
    es._hole = fake_hole
    try:
        seiten = es._alle_seiten("http://test/job/NextDocument", max_seiten=5)
    finally:
        es._hole = alt

    assert len(seiten) == 5


def test_escl_wartet_auf_bereitschaft():
    """scanne() darf nicht starten, solange ein Auftrag offen ist."""
    from app import scanner_escl as es

    # Ohne offenen Auftrag: sofort bereit.
    alt_status, alt_offen = es.status, es._auftrag_offen
    es.status = lambda url: {"bereit": True, "zustand": "Idle", "papier": True}
    es._auftrag_offen = lambda url: False
    try:
        assert es._warte_auf_bereitschaft("http://test", max_sekunden=2) is True
    finally:
        es.status, es._auftrag_offen = alt_status, alt_offen


def test_escl_wartet_nicht_endlos():
    """Bei dauerhaft offenem Auftrag endet die Wartezeit kontrolliert."""
    from app import scanner_escl as es

    alt_status, alt_offen = es.status, es._auftrag_offen
    es.status = lambda url: {"bereit": True, "zustand": "Idle", "papier": True}
    es._auftrag_offen = lambda url: True   # immer offen
    try:
        assert es._warte_auf_bereitschaft("http://test", max_sekunden=1) is False
    finally:
        es.status, es._auftrag_offen = alt_status, alt_offen


def test_escl_auftrag_offen_erkennt_offene_bilder():
    """ImagesToTransfer > 0 bedeutet: es liegen noch Bilder bereit."""
    from app import scanner_escl as es

    class FakeHole:
        def __init__(self, xml):
            self.xml = xml

        def __call__(self, url, timeout):
            return 200, self.xml.encode("utf-8")

    alt = es._hole

    # Auftrag mit offenem Bild
    es._hole = FakeHole(
        "<scan:JobInfo><pwg:JobState>Completed</pwg:JobState>"
        "<pwg:ImagesToTransfer>1</pwg:ImagesToTransfer></scan:JobInfo>"
    )
    try:
        assert es._auftrag_offen("http://test") is True
    finally:
        es._hole = alt

    # Auftrag ohne offene Bilder
    es._hole = FakeHole(
        "<scan:JobInfo><pwg:JobState>Completed</pwg:JobState>"
        "<pwg:ImagesToTransfer>0</pwg:ImagesToTransfer></scan:JobInfo>"
    )
    try:
        assert es._auftrag_offen("http://test") is False
    finally:
        es._hole = alt
