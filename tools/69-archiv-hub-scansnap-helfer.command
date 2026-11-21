#!/bin/bash
#
# Archiv Hub – ScanSnap-Helfer
#
# Der Hub läuft im Docker-Container und hat keinen USB-Zugang. Der ScanSnap
# S1500 hängt aber per USB am Mac. Dieser Helfer überbrückt das:
#
#   1. Er lauscht auf 127.0.0.1:8099.
#   2. Ruft der Hub /scan auf, öffnet er die App "Scan".
#   3. Sie scannen dort; die Datei legt die App selbst in den Eingangskorb.
#
# Einmalige Einrichtung in der App "Scan":
#   "Speichern unter" -> "Wählen..." -> diesen Ordner wählen:
#   <Projekt>/data/input
# Danach erscheint jeder Scan automatisch im Hub.
#
# Der Hub erreicht den Helfer über host.docker.internal:8099.
#
# Start: dieses Skript doppelklicken. Es läuft, bis das Fenster geschlossen
# wird. Zum Beenden Strg+C drücken.
#
set -euo pipefail

PROJECT_DIR="/Volumes/OWC 8TB/Programmieren/entwicklung/projects/archiv-hub"
KORB="$PROJECT_DIR/data/input"
PORT=8099
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin"

echo "======================================================"
echo "   Archiv Hub – ScanSnap-Helfer"
echo "======================================================"
echo
echo "Eingangskorb : $KORB"
echo "Helfer lauscht auf http://127.0.0.1:$PORT"
echo
echo "Dieses Fenster offen lassen, solange der Hub läuft."
echo "Beenden mit Strg+C."
echo

mkdir -p "$KORB"

# Diese Python-Version bringt macOS mit; keine Installation nötig.
/usr/bin/python3 - "$KORB" "$PORT" <<'PYTHON'
import http.server
import subprocess
import sys

korb = sys.argv[1]
port = int(sys.argv[2])

APP = "Scan"


class Helfer(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - Vorgabe der Basisklasse
        if self.path.rstrip("/") not in ("/health", ""):
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"archiv-hub-scansnap-helfer ok")

    def do_POST(self):  # noqa: N802 - Vorgabe der Basisklasse
        if self.path.rstrip("/") != "/scan":
            self.send_error(404)
            return

        # Die App "Scan" wird geöffnet. Sie speichert ihre Scans direkt in den
        # Eingangskorb; das Ziel ist dort einmalig unter "Speichern unter"
        # einzustellen. Ein Zugriff auf den Container der App ist nicht nötig
        # (und wäre ohne Sonderrechte auch gar nicht möglich).
        subprocess.run(["open", "-a", APP], check=False)

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):
        pass  # keine Konsolenausgabe pro Anfrage


print("Helfer bereit. Warte auf den Hub ...")
print()
try:
    http.server.HTTPServer(("127.0.0.1", port), Helfer).serve_forever()
except KeyboardInterrupt:
    print()
    print("Helfer beendet.")
PYTHON
