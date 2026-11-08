#!/bin/zsh

PROJECT="/Volumes/OWC 8TB/Programmieren/entwicklung/projects/archiv-hub"

cd "$PROJECT" || exit 1

echo "========================================"
echo " Archiv Hub – Automatischer Commit & Push"
echo "========================================"
echo

git fetch origin || exit 1

if [[ -n "$(git status --porcelain)" ]]; then
    echo "Folgende Änderungen werden übernommen:"
    echo
    git status --short
    echo

    git add -A

    MESSAGE="Automatischer Archiv-Hub-Commit $(date '+%Y-%m-%d %H:%M')"

    echo "Commit wird erstellt:"
    echo "$MESSAGE"

    git commit -m "$MESSAGE" || exit 1
    echo
else
    echo "Keine neuen Dateiänderungen zum Committen."
    echo
fi

AHEAD=$(git rev-list --count origin/main..HEAD)

if [[ "$AHEAD" -gt 0 ]]; then
    echo "$AHEAD lokale(r) Commit(s) noch nicht auf GitHub."
    echo "Push zu GitHub ..."
    git push origin main || exit 1
    echo
else
    echo "Keine ungepushten Commits vorhanden."
    echo
fi

echo "========================================"
echo " COMMIT & PUSH ABGESCHLOSSEN"
echo "========================================"
