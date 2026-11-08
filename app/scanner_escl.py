"""Scanner-Ansteuerung über eSCL (AirScan).

Der Brother MFC-L2980DW (und viele andere Netzwerk-Scanner) sprechen das
Protokoll eSCL – dasselbe, das macOS in „Digitale Bilder" verwendet. Damit
kann der Hub direkt scannen, ohne Zusatzsoftware.

Vorteil gegenüber „Digitale Bilder": Auflösung, Quelle (Flachbett/Einzug),
Duplex und Format lassen sich aus dem Hub heraus setzen.

Wichtig: Der Container braucht die IP des Scanners (ARCHIV_HUB_SCANNER_URL).
Bonjour/mDNS funktioniert in Docker auf macOS nicht.
"""

import re
import urllib.error
import urllib.request
from xml.sax.saxutils import escape

# Zeitlimits: ein Scan kann bei 600 dpi und Einzug deutlich dauern.
STATUS_TIMEOUT = 10
SCAN_TIMEOUT = 300

# Von eSCL unterstützte Werte (siehe ScannerCapabilities).
QUELLEN = {
    "flachbett": "Platen",
    "einzug": "AdfSimplex",
    "einzug-duplex": "AdfDuplex",
}

FARBMODI = {
    "farbe": "RGB24",
    "grau": "Grayscale8",
    "sw": "BlackAndWhite1",
}

AUFLOESUNGEN = (100, 200, 300, 600)


class ScannerFehler(Exception):
    """Fehler beim Ansprechen des Scanners."""


def _basis_url(url):
    url = str(url or "").strip().rstrip("/")
    if not url:
        raise ScannerFehler("Keine Scanner-Adresse konfiguriert.")
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    return url


def _hole(url, timeout, daten=None, content_type=None):
    """HTTP-Anfrage an den Scanner. Liefert die Antwortbytes."""
    req = urllib.request.Request(url)
    if daten is not None:
        req.data = daten
        req.method = "POST"
        if content_type:
            req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as antwort:
            return antwort.status, antwort.read()
    except urllib.error.HTTPError as exc:
        # 201/202 sind bei eSCL Erfolgsmeldungen ohne Body.
        if exc.code in (201, 202):
            return exc.code, b""
        raise ScannerFehler(f"Scanner antwortete mit HTTP {exc.code}.") from exc
    except urllib.error.URLError as exc:
        raise ScannerFehler(
            f"Scanner nicht erreichbar ({exc.reason}). Läuft das Gerät und "
            "stimmt die Adresse?"
        ) from exc
    except TimeoutError as exc:
        raise ScannerFehler("Zeitüberschreitung beim Scanner.") from exc


def status(url):
    """Liest den Gerätezustand. Liefert {"bereit": bool, "zustand": str}."""
    basis = _basis_url(url)
    _code, body = _hole(f"{basis}/eSCL/ScannerStatus", STATUS_TIMEOUT)
    text = body.decode("utf-8", "replace")
    treffer = re.search(r"<pwg:State>([^<]+)</pwg:State>", text)
    zustand = treffer.group(1) if treffer else "Unbekannt"
    return {"bereit": zustand.lower() == "idle", "zustand": zustand}


def scannt_noch(url):
    """Prüft, ob gerade ein Auftrag läuft (für den Fortschritt)."""
    basis = _basis_url(url)
    _code, body = _hole(f"{basis}/eSCL/ScannerStatus", STATUS_TIMEOUT)
    text = body.decode("utf-8", "replace")
    return "Processing" in text or "Pending" in text


def _scan_einstellungen(
    quelle="flachbett",
    aufloesung=300,
    farbmodus="farbe",
    duplex=False,
    format_="pdf",
):
    """Baut das eSCL-XML für einen Scanauftrag."""
    quelle_xml = QUELLEN.get(quelle)
    if quelle_xml is None:
        raise ScannerFehler(f"Unbekannte Quelle: {quelle!r}")
    if duplex and quelle == "einzug":
        quelle_xml = QUELLEN["einzug-duplex"]

    try:
        aufloesung = int(aufloesung)
    except (TypeError, ValueError):
        raise ScannerFehler("Ungültige Auflösung.") from None
    if aufloesung not in AUFLOESUNGEN:
        raise ScannerFehler(
            f"Auflösung {aufloesung} wird nicht unterstützt. "
            f"Möglich: {', '.join(str(a) for a in AUFLOESUNGEN)}."
        )

    farbe_xml = FARBMODI.get(farbmodus)
    if farbe_xml is None:
        raise ScannerFehler(f"Unbekannter Farbmodus: {farbmodus!r}")

    if format_ == "jpeg":
        mime = "image/jpeg"
    else:
        mime = "application/pdf"

    # Für den Einzug wird eine feste Breite/Höhe erwartet (A4 bei 300 dpi).
    if quelle_xml == "Platen":
        groesse = ""
    else:
        groesse = (
            "<pwg:InputSource>Feeder</pwg:InputSource>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"'
        ' xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">'
        "<pwg:Version>2.6</pwg:Version>"
        f"<pwg:ScanRegions><pwg:ScanRegion>"
        f"<pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>"
        f"<pwg:Width>2481</pwg:Width><pwg:Height>3507</pwg:Height>"
        f"<pwg:XOffset>0</pwg:XOffset><pwg:YOffset>0</pwg:YOffset>"
        f"</pwg:ScanRegion></pwg:ScanRegions>"
        f"<pwg:DocumentFormat>{mime}</pwg:DocumentFormat>"
        f"<scan:ColorMode>{farbe_xml}</scan:ColorMode>"
        f"<scan:InputSource>{quelle_xml}</scan:InputSource>"
        f"<scan:XResolution>{aufloesung}</scan:XResolution>"
        f"<scan:YResolution>{aufloesung}</scan:YResolution>"
        f"{groesse}"
        "</scan:ScanSettings>"
    )


def scanne(
    url,
    quelle="flachbett",
    aufloesung=300,
    farbmodus="farbe",
    duplex=False,
    format_="pdf",
):
    """Löst einen Scan aus und liefert die Rohdaten (PDF oder JPEG).

    Ablauf nach eSCL: POST auf /eSCL/ScanJobs legt den Auftrag an und liefert
    im Location-Header die Job-URL. Der anschliessende Aufruf von
    <job>/NextDocument blockiert, bis die Seite gescannt ist, und liefert die
    Daten. Wichtig: NextDocument muss DIREKT nach dem Anlegen aufgerufen
    werden – der Auftrag wird nach Abschluss verworfen und ist danach nicht
    mehr abholbar (getestet mit Brother MFC-L2980DW).
    """
    basis = _basis_url(url)

    zustand = status(url)
    if not zustand["bereit"]:
        raise ScannerFehler(
            f"Der Scanner ist nicht bereit (Zustand: {zustand['zustand']}). "
            "Läuft noch ein Auftrag?"
        )

    xml = _scan_einstellungen(quelle, aufloesung, farbmodus, duplex, format_)

    # Auftrag anlegen – die Job-URL steht im Location-Header.
    req = urllib.request.Request(f"{basis}/eSCL/ScanJobs")
    req.data = xml.encode("utf-8")
    req.method = "POST"
    req.add_header("Content-Type", "text/xml")
    try:
        with urllib.request.urlopen(req, timeout=SCAN_TIMEOUT) as antwort:
            job_url = antwort.headers.get("Location")
    except urllib.error.HTTPError as exc:
        if exc.code in (201, 202):
            job_url = exc.headers.get("Location")
        else:
            raise ScannerFehler(
                f"Der Scanner nahm den Auftrag nicht an (HTTP {exc.code})."
            ) from exc
    except urllib.error.URLError as exc:
        raise ScannerFehler(f"Scanner nicht erreichbar ({exc.reason}).") from exc

    if not job_url:
        raise ScannerFehler("Der Scanner lieferte keine Auftragsadresse.")

    # Seite abholen – dieser Aufruf wartet, bis der Scan fertig ist.
    _code, daten = _hole(f"{job_url.rstrip('/')}/NextDocument", SCAN_TIMEOUT)

    if not daten:
        raise ScannerFehler("Der Scanner hat keine Daten geliefert.")
    if not daten.startswith(b"%PDF") and not daten.startswith(b"\xff\xd8"):
        raise ScannerFehler("Der Scanner lieferte kein gültiges PDF/JPEG.")

    return daten, ("application/pdf" if format_ != "jpeg" else "image/jpeg")
