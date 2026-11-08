#!/bin/bash
#
# Archiv Hub – Scannen
#
# Öffnet "Digitale Bilder" (Image Capture) und zeigt den Eingangskorb.
# Der Scan selbst läuft in "Digitale Bilder" – dort einmalig als Ziel
# "Scannen in: Anderer Ordner…" den Eingangskorb wählen.
#
# Legt KEINE Dateien an ausser dem Eingangskorb-Ordner selbst.
#
set -euo pipefail

PROJECT_DIR="/Volumes/OWC 8TB/Programmieren/entwicklung/projects/archiv-hub"
KORB="$PROJECT_DIR/data/input"
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin"

echo "======================================================"
echo "   Archiv Hub – Scannen"
echo "======================================================"
echo

if [ ! -d "$PROJECT_DIR" ]; then
    echo "✗ Projektordner nicht gefunden:"
    echo "  $PROJECT_DIR"
    read -r -p "Enter drücken ..."
    exit 1
fi

# Eingangskorb sicherstellen. Als normaler Benutzer anlegen, damit Docker die
# Dateien nicht als root-eigen zurücklässt.
mkdir -p "$KORB"

echo "Eingangskorb:"
echo "  $KORB"
echo

# Prüfen, ob der Hub läuft – sonst nützt der Scan wenig.
if ! /usr/bin/curl -fsS --max-time 3 "http://localhost:8002/health" >/dev/null 2>&1; then
    echo "⚠ Der Archiv Hub antwortet nicht auf http://localhost:8002"
    echo "  Starte ihn zuerst mit:"
    echo "  60-archiv-hub-A-starten.command"
    echo
    read -r -p "Trotzdem 'Digitale Bilder' öffnen? [j/N] " ANTWORT
    [[ "$ANTWORT" == [jJ] ]] || { echo "Abgebrochen."; exit 0; }
fi

echo "▶ Öffne 'Digitale Bilder' ..."
open -a "Image Capture" 2>/dev/null || open -a "Digitale Bilder" 2>/dev/null || {
    echo "✗ 'Digitale Bilder' konnte nicht geöffnet werden."
    read -r -p "Enter drücken ..."
    exit 1
}

echo
echo "──────────────────────────────────────────────────────"
echo " So scannen:"
echo "──────────────────────────────────────────────────────"
echo
echo " 1) Scanner links auswählen (z. B. Brother MFC-L2980DW)"
echo
echo " 2) Rechts einstellen:"
echo "      Scan-Modus   : Dokumenteinzug  (oder Flachbett)"
echo "      Auflösung    : 300 dpi"
echo "      Größe        : A4"
echo "      Duplex       : nur wenn beidseitig nötig"
echo "      Format       : PDF"
echo "      OCR          : aus  (der Hub erkennt den Text selbst)"
echo
echo " 3) 'Scannen in' einmalig auf diesen Ordner stellen:"
echo "      $KORB"
echo
echo " 4) 'Scannen' drücken"
echo
echo " 5) Danach im Hub auf 'Aktualisieren' klicken –"
echo "    der Scan erscheint im Eingangskorb."
echo
echo "──────────────────────────────────────────────────────"
echo

# Finder mit dem Korb öffnen, damit der Ordner leicht zu finden ist.
open "$KORB" 2>/dev/null || true

read -r -p "Enter drücken ..."
