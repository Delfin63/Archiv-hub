#!/usr/bin/env python
"""Erzeugt einen Passwort-Hash für die Umgebungsvariable ARCHIV_HUB_PASSWORD_HASH.

Aufruf (im Projektverzeichnis, z. B. mit dem Projekt-venv):
    .venv/bin/python generate-password-hash.py

Das Passwort wird interaktiv abgefragt und erscheint nicht im Terminal.
Die Ausgabe ist der Hash, der in .env unter ARCHIV_HUB_PASSWORD_HASH eingetragen wird.
"""

import getpass
import sys

from werkzeug.security import generate_password_hash


def main():
    password = getpass.getpass("Passwort: ")
    if not password:
        print("Kein Passwort angegeben.", file=sys.stderr)
        return 1
    confirmation = getpass.getpass("Passwort wiederholen: ")
    if password != confirmation:
        print("Die Passwörter stimmen nicht überein.", file=sys.stderr)
        return 1
    print(generate_password_hash(password))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
