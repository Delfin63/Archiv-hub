"""Klassifizierung von Dokumenten per LLM.

Technische Anbindung wie healing-hub/app/summarizer.py: OpenAI-kompatibler
Client (``openai``), API-Key aus ``DEEPSEEK_API_KEY``, Basis-URL/Modell aus
``DEEPSEEK_BASE_URL``/``DEEPSEEK_MODEL`` mit Defaults aus settings.yaml.
Der Client wird erst bei Bedarf importiert, damit Tests ohne ``openai`` laufen.
"""

import json
import os
import re

from . import config

MAX_TEXT_CHARS = 4000

SYSTEM_PROMPT = """Du ordnest Dokumente für ein Archiv vor.

Du erhältst einen Dokumenttext und eine Liste der bereits vorhandenen Ordner.
Schlage den passenden Ordner vor.

Wähle einen vorhandenen Ordner, wenn er inhaltlich passt, und gib seine id an.
Passt kein vorhandener Ordner, schlage einen NEUEN Ordnernamen vor: kurz,
deutsch, ohne Datum. Umlaute (ä, ö, ü) und ß sind ausdrücklich erlaubt und
erwünscht – schreibe sie so, wie sie im Dokument stehen, nicht als ae/oe/ue.
Beispiele: "Rechnungen", "Arztberichte", "Übungsanleitungen", "Prämien".

Antworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt. Keine Einleitung,
keine Markdown-Codeblöcke, keine Kommentare, keine Rückfragen.

Das JSON-Objekt muss genau diese Felder enthalten:

- "ziel_id": id eines vorhandenen Ordners (exakt) oder "neu" bei neuem Vorschlag
- "ordner": Name des vorgeschlagenen Ordners (bei vorhandenem Ordner: sein Name)
- "datum": das DOKUMENTDATUM im Format YYYY-MM-DD. Verwende das Datum, das im
  Dokument steht (z. B. Rechnungsdatum, Briefdatum, Ausstellungsdatum) – NICHT
  das heutige Datum. Nur wenn im Dokument kein Datum vorkommt, lass das Feld
  leer ("").
- "dokumentname": der KURZE, INHALTLICHE Name des Dokuments – worum es konkret
  geht, nicht die Gattung. Beispiele: "Ischias", "Muster AG", "Steuererklärung
  2025", "Bandscheibenvorfall". NICHT "Übungsanleitung" oder "Rechnung" (das
  wäre der Typ). Umlaute sind erlaubt. Höchstens 40 Zeichen, ohne Datum.
- "absender": Absender/Aussteller des Dokuments (Firmenname, Praxis, Behörde)
- "dokumenttyp": der Dokumenttyp (z. B. Rechnung, Vertrag, Arztbrief)
- "sicherheit": eine Zahl zwischen 0 und 1 für deine Zuordnungssicherheit

Beispiele:
{"ziel_id": "abc123", "ordner": "Rechnungen", "datum": "2026-11-07",
 "dokumentname": "Muster AG Serverwartung",
 "absender": "Musterpraxis", "dokumenttyp": "Rechnung", "sicherheit": 0.92}

{"ziel_id": "neu", "ordner": "Uebungsanleitungen", "datum": "",
 "dokumentname": "Ischias", "absender": "", "dokumenttyp": "Uebungsanleitung",
 "sicherheit": 0.9}"""


def _chat(messages, temperature=0.1, max_tokens=1000):
    """Ein einzelner LLM-Aufruf. ``openai`` wird erst hier importiert."""
    from openai import OpenAI

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError(
            "DeepSeek API-Key fehlt. Bitte die Umgebungsvariable "
            "DEEPSEEK_API_KEY setzen."
        )

    client = OpenAI(api_key=api_key, base_url=config.get_llm_base_url())
    response = client.chat.completions.create(
        model=config.get_llm_model(),
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        extra_body={"thinking": {"type": "disabled"}},
    )
    return response.choices[0].message.content or ""


def _extract_json(text):
    """Zieht das erste JSON-Objekt aus einer LLM-Antwort. Wirft ValueError bei
    ungültigem JSON."""
    text = (text or "").strip()

    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("Kein JSON-Objekt in der LLM-Antwort gefunden.")

    return json.loads(text[start : end + 1])


def _build_messages(text, ziele, ordner=None):
    """Baut die LLM-Nachrichten.

    ``ziele``: vorhandene Ablageziele (id, name, beschreibung).
    ``ordner``: zusätzliche Ordnernamen im Archiv, die noch kein Ziel sind.
    """
    zeilen = []
    for ziel in ziele:
        zeilen.append(
            "- id=%s | name=%s | beschreibung=%s"
            % (
                ziel.get("id"),
                ziel.get("name") or "",
                ziel.get("beschreibung") or "",
            )
        )
    if not zeilen:
        zeilen.append("(noch keine Ordner vorhanden – schlage einen neuen vor)")

    vorhandene = ""
    if ordner:
        vorhandene = (
            "\n\nWeitere Ordner, die im Archiv bereits existieren "
            "(ohne eigene Beschreibung):\n"
            + "\n".join("- " + str(o) for o in ordner)
        )

    user = (
        "Vorhandene Ordner:\n"
        + "\n".join(zeilen)
        + vorhandene
        + "\n\nDokumenttext:\n"
        + text
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def classify(text, ziele, ordner=None):
    """Klassifiziert einen Dokumenttext.

    Liefert ein dict mit ziel_id, ordner, datum, absender, dokumenttyp,
    sicherheit. Bei ungültigem JSON wird genau einmal erneut versucht.
    """
    text = (text or "").strip()[:MAX_TEXT_CHARS]
    messages = _build_messages(text, ziele, ordner)

    raw = _chat(messages)
    try:
        return _extract_json(raw)
    except (ValueError, json.JSONDecodeError):
        messages.append({"role": "assistant", "content": raw})
        messages.append(
            {
                "role": "user",
                "content": (
                    "Deine Antwort war kein gültiges JSON. Antworte erneut "
                    "AUSSCHLIESSLICH mit dem JSON-Objekt."
                ),
            }
        )
        raw = _chat(messages)
        return _extract_json(raw)
