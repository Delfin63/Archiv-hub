FROM python:3.12-slim

# Robustere apt-Aufrufe: mehr Wiederholungen und keine HTTP-Pipeline, um
# "Hash Sum mismatch" bei Netzwerkproblemen beim Download zu vermeiden.
RUN printf 'Acquire::Retries "5";\nAcquire::http::Pipeline-Depth "0";\n' \
        > /etc/apt/apt.conf.d/99-robust

# Tesseract OCR (deu+eng) und die von OCRmyPDF benötigten Systemprogramme.
# unpaper wird NICHT installiert: es wird nicht verwendet und würde über die
# FFmpeg-Bibliotheken 100+ zusätzliche Pakete nachziehen.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-deu \
        tesseract-ocr-eng \
        ghostscript \
        qpdf \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# requirements.txt zuerst, damit Docker die Pip-Schicht zwischenspeichern kann.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

CMD ["gunicorn", "--preload", "--bind", "0.0.0.0:8000", "--timeout", "600", "--access-logfile", "-", "app.app:app"]
