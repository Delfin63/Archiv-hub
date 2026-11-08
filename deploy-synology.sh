#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Archiv Hub – Synology Deploy-Skript
#
# Überträgt den Archiv Hub per SSH/rsync auf die Synology NAS und startet den
# Container neu. Produktive Daten (data/, .env) bleiben unangetastet.
#
# Prozessor-Architektur (Mac Apple-Chip vs. Synology x86):
# Es wird ausschliesslich architekturunabhängiger Quellcode übertragen. Das
# Docker-Image wird erst auf dem Zielgerät mit "docker compose up -d --build"
# gebaut und läuft damit nativ auf der jeweiligen CPU. Ein --platform-Flag ist
# deshalb nicht nötig (gleiche Lösung wie in den anderen Hubs).
#
# Zielstruktur auf der NAS:
#   /volume1/docker/archiv-hub/
#   ├── app/
#   ├── docker/
#   ├── data/
#   ├── .dockerignore
#   ├── requirements.txt
#   └── compose.yaml
# =============================================================================

SYNOLOGY_HOST="${SYNOLOGY_HOST:-synology-tailscale}"
SYNOLOGY_USER="${SYNOLOGY_USER:-}"
SYNOLOGY_SSH_PORT="${SYNOLOGY_SSH_PORT:-22}"
SYNOLOGY_DOCKER_COMPOSE="${SYNOLOGY_DOCKER_COMPOSE:-/usr/local/bin/docker compose}"

TARGET="/volume1/docker/archiv-hub"
# Ablage-Basis (ARCHIV_HUB_ABLAGE_BASIS) wird NICHT hier gesetzt, sondern in
# der .env auf der Synology (/volume1/docker/archiv-hub/.env) konfiguriert.
# data/ (ziele.json, speicherorte.json, archiv.log, zur-pruefung) und
# compose.speicherorte.yaml werden bewusst NICHT übertragen – die Synology
# hat eigene Speicherorte (siehe README.md).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SSH_TARGET="$SYNOLOGY_HOST"
[[ -n "$SYNOLOGY_USER" ]] && SSH_TARGET="$SYNOLOGY_USER@$SYNOLOGY_HOST"

SSH_OPTS=(-p "$SYNOLOGY_SSH_PORT" -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new)
RSYNC_RSH="ssh -p ${SYNOLOGY_SSH_PORT} -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new"

run_ssh() { ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "$@"; }

echo "Prüfe SSH-Verbindung zu ${SSH_TARGET} ..."
run_ssh true || { echo "FEHLER: SSH-Verbindung fehlgeschlagen."; exit 1; }

echo "Bereite Zielordner auf der Synology vor ..."
run_ssh "mkdir -p '$TARGET/app' '$TARGET/docker' '$TARGET/data/zur-pruefung' '$TARGET/data/input'"

echo "Übertrage Archiv Hub ..."

# Programmcode
rsync -a --delete \
  --exclude '.DS_Store' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  -e "$RSYNC_RSH" \
  app/ "$SSH_TARGET:$TARGET/app/"

# Docker-Dateien
rsync -a --delete \
  --exclude '.DS_Store' \
  -e "$RSYNC_RSH" \
  docker/ "$SSH_TARGET:$TARGET/docker/"

# Hauptdateien
rsync -a \
  -e "$RSYNC_RSH" \
  requirements.txt \
  compose.yaml \
  .dockerignore \
  "$SSH_TARGET:$TARGET/"

echo "Baue/starte Archiv Hub neu (Image wird auf der Synology gebaut) ..."
run_ssh sh -s <<REMOTE_EOF
set -e
cd "$TARGET"
# Ablage-Basis der Synology (.env) zu einem absoluten Pfad auflösen und dem
# Container nur zur Anzeige mitgeben. Der Mount bleibt unverändert.
ABLAGE_BASIS="\$(sed -n 's/^ARCHIV_HUB_ABLAGE_BASIS=//p' .env | tail -1)"
[ -n "\$ABLAGE_BASIS" ] || ABLAGE_BASIS="./data/ablage"
mkdir -p "\$ABLAGE_BASIS"
export ARCHIV_HUB_ABLAGE_BASIS_ANZEIGE="\$(cd "\$ABLAGE_BASIS" && pwd -P)"
if [ -f compose.speicherorte.yaml ]; then
  $SYNOLOGY_DOCKER_COMPOSE -f compose.yaml -f compose.speicherorte.yaml up -d --build
else
  $SYNOLOGY_DOCKER_COMPOSE up -d --build
fi
REMOTE_EOF

echo
echo "Archiv Hub erfolgreich aktualisiert."
