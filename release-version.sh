#!/bin/zsh
set -euo pipefail

PROJECT="/Volumes/OWC 8TB/Programmieren/entwicklung/projects/archiv-hub"
RELEASE_ROOT="/Volumes/OWC 8TB/Programmieren/entwicklung/releases/archiv-hub"
BRANCH="main"

cd "$PROJECT"

fail() {
  echo
  echo "ABBRUCH: $1"
  echo "Es wurde nichts automatisch verworfen oder überschrieben."
  read "?Enter zum Schliessen ..."
  exit 1
}

echo "===================================="
echo " Archiv Hub – Version abschliessen"
echo "===================================="
echo

CURRENT_BRANCH="$(git branch --show-current)"
[[ "$CURRENT_BRANCH" == "$BRANCH" ]] || fail "Falscher Branch: $CURRENT_BRANCH"

[[ -z "$(git status --porcelain)" ]] || fail "Working Tree ist nicht sauber."

git fetch origin "$BRANCH" --tags >/dev/null 2>&1 || fail "GitHub konnte nicht abgefragt werden."

LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"
[[ "$LOCAL" == "$REMOTE" ]] || fail "Lokaler Stand und GitHub sind nicht synchron."

VERSION="$(tr -d '[:space:]' < app/version.txt)"
[[ "$VERSION" =~ '^[0-9]+\.[0-9]+$' ]] || fail "Versionsnummer konnte nicht erkannt werden."

MAJOR="${VERSION%%.*}"
MINOR="${VERSION##*.}"

NORMAL_NEXT="$MAJOR.$((MINOR + 1))"
MAJOR_NEXT="$((MAJOR + 1)).0"

echo
echo "Welche Version soll nach Abschluss von $VERSION eröffnet werden?"
echo
echo "1) Normale neue Version  → $NORMAL_NEXT"
echo "2) Neue Hauptversion     → $MAJOR_NEXT"
echo "3) Versionsnummer selbst eingeben"
echo "4) Abbrechen"
echo
read "?Auswahl [1-4]: "

case "$REPLY" in
  1)
    NEXT="$NORMAL_NEXT"
    ;;
  2)
    NEXT="$MAJOR_NEXT"
    ;;
  3)
    while true; do
      read "?Neue Versionsnummer: " NEXT

      if [[ ! "$NEXT" =~ '^[0-9]+\.[0-9]+$' ]]; then
        echo "Ungültiges Format. Beispiel: 2.0"
        continue
      fi

      NEXT_MAJOR="${NEXT%%.*}"
      NEXT_MINOR="${NEXT##*.}"

      if (( NEXT_MAJOR > MAJOR || (NEXT_MAJOR == MAJOR && NEXT_MINOR > MINOR) )); then
        break
      fi

      echo "Die neue Version muss höher als $VERSION sein."
    done
    ;;
  4)
    echo
    echo "Abgebrochen. Es wurde nichts verändert."
    exit 0
    ;;
  *)
    echo
    echo "Ungültige Auswahl. Es wurde nichts verändert."
    exit 1
    ;;
esac

TAG="v$VERSION"
RELEASE_DIR="$RELEASE_ROOT/Archiv Hub v$VERSION"

git rev-parse "$TAG" >/dev/null 2>&1 && fail "Tag $TAG existiert bereits."
[[ ! -e "$RELEASE_DIR" ]] || fail "Release-Ordner existiert bereits: $RELEASE_DIR"

echo
echo "Aktuelle Version : $VERSION"
echo "Neue Version     : $NEXT"
echo "Release-Ordner   : $RELEASE_DIR"
echo
read "?Version $VERSION wirklich abschliessen? [j/N] "
[[ "$REPLY" == [jJ] ]] || fail "Vom Benutzer abgebrochen."

echo
echo "Erstelle Release-Tag ..."
git tag -a "$TAG" -m "Version $VERSION"

echo "Übertrage Tag zu GitHub ..."
git push origin "$TAG"

echo "Erstelle Release-Sicherung ..."
mkdir "$RELEASE_DIR"
git archive "$TAG" | tar -x -C "$RELEASE_DIR"

SAVED="$(tr -d '[:space:]' < "$RELEASE_DIR/app/version.txt")"
[[ "$SAVED" == "$VERSION" ]] || fail "Versionsprüfung der Release-Sicherung fehlgeschlagen."

echo "Eröffne Version $NEXT ..."
printf "%s\n" "$NEXT" > app/version.txt

[[ "$(tr -d '[:space:]' < app/version.txt)" == "$NEXT" ]] || fail "Neue Versionsnummer wurde nicht korrekt gesetzt."

git add app/version.txt
git commit -m "Version $NEXT – Entwicklung gestartet"
git push origin "$BRANCH"

[[ -z "$(git status --porcelain)" ]] || fail "Working Tree ist nach dem Release nicht sauber."

echo
echo "===================================="
echo " ERFOLGREICH"
echo "===================================="
echo "Abgeschlossen : Version $VERSION"
echo "Tag           : $TAG"
echo "Release       : $RELEASE_DIR"
echo "Neue Version  : $NEXT"
echo "GitHub        : aktualisiert"
echo
read "?Enter zum Schliessen ..."
