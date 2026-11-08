"""Texterkennung mit OCRmyPDF/Tesseract (deu+eng).

Ergebnis ist ein durchsuchbares PDF plus der extrahierte Volltext. Läuft im
Docker-Container mit OCRmyPDF und Tesseract. Ohne OCRmyPDF (nur lokale Tests)
wird für bereits durchsuchbare PDFs die Textschicht direkt ausgelesen.
"""

import shutil
import subprocess
from pathlib import Path

OCR_LANGS = "deu+eng"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def has_ocrmypdf():
    return shutil.which("ocrmypdf") is not None


def image_to_pdf(image_path, pdf_path):
    """Konvertiert ein Bild nach PDF (RGB), damit OCRmyPDF es verarbeiten kann."""
    from PIL import Image

    with Image.open(image_path) as image:
        if image.mode in ("RGBA", "P", "LA"):
            image = image.convert("RGB")
        elif image.mode != "RGB":
            image = image.convert("RGB")
        image.save(pdf_path, "PDF", resolution=300.0)


def _run_ocrmypdf(input_pdf, output_pdf, sidecar):
    command = [
        "ocrmypdf",
        "--skip-text",
        "--deskew",
        "--sidecar",
        str(sidecar),
        "-l",
        OCR_LANGS,
        str(input_pdf),
        str(output_pdf),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)


def _extract_text_layer(pdf_path):
    """Liest die Textschicht eines durchsuchbaren PDFs (Fallback ohne OCRmyPDF)."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def process(input_path, work_dir):
    """Erkennt Text aus PDF oder Bild.

    Gibt ``(searchable_pdf_path, text)`` zurück. ``work_dir`` dient als
    Arbeitsverzeichnis für Zwischendateien.
    """
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    source = Path(input_path)
    suffix = source.suffix.lower()

    if suffix in IMAGE_EXTENSIONS:
        pdf = work_dir / (source.stem + ".pdf")
        image_to_pdf(source, pdf)
    else:
        pdf = source

    output_pdf = work_dir / "searchable.pdf"
    sidecar = work_dir / "text.txt"

    if has_ocrmypdf():
        _run_ocrmypdf(pdf, output_pdf, sidecar)
    else:
        shutil.copyfile(pdf, output_pdf)
        sidecar.write_text(_extract_text_layer(pdf), "utf-8")

    text = sidecar.read_text("utf-8") if sidecar.exists() else ""
    return output_pdf, text
