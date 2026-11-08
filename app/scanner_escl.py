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
import time
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

# Brother-Scanner brauchen zwischen zwei Seitenabrufen eine kurze Pause,
# sonst kommt fälschlich HTTP 404 und der Auftrag endet nach Seite 1.
# (sane-airscan verwendet 1000 ms, begrenzt auf die halbe Dauer des
# vorherigen Abrufs.)
NEXT_LOAD_DELAY = 1.0

# Wie oft ein fehlgeschlagener Seitenabruf wiederholt wird, solange der
# Auftrag beim Scanner noch offen ist (sane-airscan: 30 Versuche).
NEXT_LOAD_VERSUCHE = 30

# Aufträge, die älter sind, gelten als Karteileichen. Der Scanner räumt seine
# Job-Liste nicht auf; alte Einträge melden dauerhaft offene Bilder.
JOB_MAX_ALTER = 600   # Sekunden

# A4 (210 x 297 mm) in 1/300 Zoll – so erwartet es eSCL für ScanRegions.
REGION_BREITE = 2480
REGION_HOEHE = 3508


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
    """Liest den Gerätezustand.

    Liefert {"bereit": bool, "zustand": str, "papier": bool}.

    "bereit" ist auch dann True, wenn das Gerät gerade "Processing" meldet,
    aber Papier im Einzug liegt. Der Brother MFC-L2980DW zeigt nach einem
    Auftrag rund eine Minute "Processing", obwohl ein neuer Scan bereits
    möglich wäre – ein gesperrter Scan-Knopf wäre dann irreführend.
    """
    basis = _basis_url(url)
    _code, body = _hole(f"{basis}/eSCL/ScannerStatus", STATUS_TIMEOUT)
    text = body.decode("utf-8", "replace")

    treffer = re.search(r"<pwg:State>([^<]+)</pwg:State>", text)
    zustand = treffer.group(1) if treffer else "Unbekannt"

    adf = re.search(r"AdfState>([^<]+)</", text)
    adf_zustand = adf.group(1) if adf else ""
    papier = adf_zustand == "ScannerAdfLoaded"

    bereit = zustand.lower() == "idle" or papier
    return {"bereit": bereit, "zustand": zustand, "papier": papier}


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

    # sane-airscan sendet für beide Einzug-Varianten "Feeder".
    quelle_pwg = "Platen" if quelle_xml == "Platen" else "Feeder"

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

    # Quelle und Duplex nach dem Vorbild von sane-airscan:
    #   Flachbett -> Platen
    #   Einzug    -> Feeder  (NICHT "AdfSimplex"!)
    # Duplex wird separat über scan:Duplex mitgeteilt.
    if quelle_xml == "Platen":
        quelle_zusatz = ""
    else:
        quelle_zusatz = f"<scan:Duplex>{'true' if duplex else 'false'}</scan:Duplex>"

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<scan:ScanSettings xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03"'
        ' xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm">'
        "<pwg:Version>2.6</pwg:Version>"
        "<pwg:ScanRegions><pwg:ScanRegion>"
        # Die Region wird IMMER in 1/300 Zoll angegeben – unabhängig von der
        # eingestellten Auflösung. 2480 x 3508 entspricht A4 (210 x 297 mm).
        "<pwg:ContentRegionUnits>escl:ThreeHundredthsOfInches</pwg:ContentRegionUnits>"
        f"<pwg:Width>{REGION_BREITE}</pwg:Width>"
        f"<pwg:Height>{REGION_HOEHE}</pwg:Height>"
        "<pwg:XOffset>0</pwg:XOffset>"
        "<pwg:YOffset>0</pwg:YOffset>"
        "</pwg:ScanRegion></pwg:ScanRegions>"
        f"<pwg:DocumentFormat>{mime}</pwg:DocumentFormat>"
        f"<scan:ColorMode>{farbe_xml}</scan:ColorMode>"
        f"<pwg:InputSource>{quelle_pwg}</pwg:InputSource>"
        f"<scan:XResolution>{aufloesung}</scan:XResolution>"
        f"<scan:YResolution>{aufloesung}</scan:YResolution>"
        # Beim Einzug: scan:Duplex (true/false), beim Flachbett leer.
        f"{quelle_zusatz}"
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

    # Warten, bis der Scanner wirklich frei ist. Nach einem Auftrag meldet
    # der Brother rund eine Minute "Processing"; ein sofortiger neuer Auftrag
    # kann sonst einen alten, unvollständigen Job liefern (beobachtet:
    # Antwort nach 0 s mit nur einer Seite).
    if not _warte_auf_bereitschaft(url):
        zustand = status(url)
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

    # Seiten abholen: bei Einzug liefert der Scanner mehrere Seiten nacheinander.
    # Jeder Aufruf von NextDocument wartet, bis die nächste Seite fertig ist,
    # und liefert sie. Sind keine Seiten mehr da, kommt HTTP 404/410.
    seiten = _alle_seiten(f"{job_url.rstrip('/')}/NextDocument")

    if not seiten:
        raise ScannerFehler("Der Scanner hat keine Daten geliefert.")

    mime = "application/pdf" if format_ != "jpeg" else "image/jpeg"
    for seite in seiten:
        if not (seite.startswith(b"%PDF") or seite.startswith(b"\xff\xd8")):
            raise ScannerFehler("Der Scanner lieferte kein gültiges PDF/JPEG.")

    if len(seiten) == 1:
        return seiten[0], mime

    # Mehrere Seiten zu einem PDF zusammenführen.
    if format_ == "jpeg":
        # Bei JPEG bleibt nur die erste Seite – Bildformate kennen keine Seiten.
        return seiten[0], mime

    return _seiten_zusammenfuehren(seiten), "application/pdf"


def _warte_auf_bereitschaft(url, max_sekunden=90):
    """Wartet, bis der Scanner keinen Auftrag mehr offen hat.

    Liefert True, wenn er bereit ist. Während der Wartezeit wird alle zwei
    Sekunden nachgefragt.
    """
    ende = time.time() + max_sekunden
    while time.time() < ende:
        try:
            zustand = status(url)
        except ScannerFehler:
            return False
        if zustand["zustand"].lower() == "idle" and not _auftrag_offen(url):
            return True
        time.sleep(2)
    return False


def _auftrag_offen(url):
    """True, wenn beim Scanner noch ein Auftrag mit offenen Bildern läuft."""
    basis = _basis_url(url)
    try:
        _code, body = _hole(f"{basis}/eSCL/ScannerStatus", STATUS_TIMEOUT)
    except ScannerFehler:
        return False
    text = body.decode("utf-8", "replace")
    for block in re.findall(r"<scan:JobInfo>(.*?)</scan:JobInfo>", text, re.DOTALL):
        # Nur aktuelle Aufträge zählen. Der Brother MFC-L2980DW räumt seine
        # Job-Liste nicht auf: alte Einträge bleiben mit
        # ImagesToTransfer=1 stehen, obwohl der Auftrag längst beendet ist.
        alter = re.search(r"<scan:Age>(\d+)</scan:Age>", block)
        if alter and int(alter.group(1)) > JOB_MAX_ALTER:
            continue

        offen = re.search(r"<pwg:ImagesToTransfer>(\d+)</pwg:ImagesToTransfer>", block)
        if offen and int(offen.group(1)) > 0:
            return True
        zustand = re.search(r"<pwg:JobState>([^<]+)</pwg:JobState>", block)
        if zustand and zustand.group(1).strip() in ("Pending", "Processing"):
            return True
    return False


def _seiten_offen(job_url):
    """Prüft beim Scanner, ob der Auftrag noch Seiten liefern will.

    Liefert True, wenn der Job noch läuft oder noch Bilder bereitstehen.
    """
    basis = job_url.split("/eSCL/")[0]
    try:
        _code, body = _hole(f"{basis}/eSCL/ScannerStatus", STATUS_TIMEOUT)
    except ScannerFehler:
        return False
    text = body.decode("utf-8", "replace")
    # Der Job, der zu dieser URL gehört, muss noch offen sein.
    kennung = job_url.rstrip("/").split("/")[-1]
    for block in re.findall(r"<scan:JobInfo>(.*?)</scan:JobInfo>", text, re.DOTALL):
        if kennung not in block:
            continue
        # Entscheidend ist, ob noch Bilder bereitstehen. Der JobState kann
        # bereits "Completed" sein, während ImagesToTransfer noch > 0 ist –
        # der Brother MFC-L2980DW verhält sich so.
        offen = re.search(r"<pwg:ImagesToTransfer>(\d+)</pwg:ImagesToTransfer>", block)
        if offen and int(offen.group(1)) > 0:
            return True
        zustand = re.search(r"<pwg:JobState>([^<]+)</pwg:JobState>", block)
        if zustand and zustand.group(1).strip() in ("Pending", "Processing"):
            return True
    return False


def _alle_seiten(job_url, max_seiten=100):
    """Holt alle Seiten eines Auftrags.

    Brother-Geräte (u. a. MFC-L2980DW, MFC-L2710DW) antworten zwischen zwei
    Seiten sporadisch mit HTTP 404, obwohl noch Seiten im Einzug liegen.
    Deshalb wird nach einem Fehler NICHT sofort abgebrochen: Es wird beim
    Scanner nachgefragt und bei Bedarf bis zu ``NEXT_LOAD_VERSUCHE`` mal
    erneut versucht. Vorgehen wie in sane-airscan (airscan-escl.c,
    ESCL_RETRY_ATTEMPTS_LOAD).
    """
    seiten = []
    fehlversuche = 0

    for nummer in range(max_seiten):
        if nummer > 0:
            time.sleep(NEXT_LOAD_DELAY)
        try:
            _code, daten = _hole(job_url, SCAN_TIMEOUT)
        except ScannerFehler:
            # Kein Bild geliefert. Nur aufgeben, wenn der Auftrag wirklich
            # beendet ist – sonst erneut versuchen.
            if _seiten_offen(job_url) and fehlversuche < NEXT_LOAD_VERSUCHE:
                fehlversuche += 1
                continue
            break
        if not daten:
            if _seiten_offen(job_url) and fehlversuche < NEXT_LOAD_VERSUCHE:
                fehlversuche += 1
                continue
            break
        # Seite erhalten: Fehlerzähler zurücksetzen.
        fehlversuche = 0
        seiten.append(daten)

    return seiten


def _seiten_zusammenfuehren(seiten):
    """Führt mehrere Ein-Seiten-PDFs zu einem PDF zusammen."""
    import io

    from pypdf import PdfReader, PdfWriter

    schreiber = PdfWriter()
    for daten in seiten:
        leser = PdfReader(io.BytesIO(daten))
        for seite in leser.pages:
            schreiber.add_page(seite)

    ausgabe = io.BytesIO()
    schreiber.write(ausgabe)
    return ausgabe.getvalue()
