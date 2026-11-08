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

SYSTEM_PROMPT = """Du ordnest Dokumente automatisch einem Ziel zu.

Du erhältst einen Dokumenttext und eine Liste der aktiven Ziele. Wähle das
Ziel, das am besten passt. Passt kein Ziel, antworte mit ziel_id "unklar".

Antworte AUSSCHLIESSLICH mit einem gültigen JSON-Objekt. Keine Einleitung,
keine Markdown-Codeblöcke, keine Kommentare, keine Rückfragen.

Das JSON-Objekt muss genau diese Felder enthalten:

- "ziel_id": die id eines Ziels aus der Liste (exakt) oder "unklar"
- "datum": das Dokumentdatum im Format YYYY-MM-DD
- "absender": Absender/Aussteller des Dokuments
- "dokumenttyp": der Dokumenttyp (z. B. Rechnung, Vertrag, Arztbrief)
- "sicherheit": eine Zahl zwischen 0 und 1 für deine Zuordnungssicherheit

Beispiel:
{"ziel_id": "abc123", "datum": "2026-11-07",
 "absender": "Musterpraxis", "dokumenttyp": "Rechnung", "sicherheit": 0.92}"""


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


def _build_messages(text, ziele):
    ziel_lines = "\n".join(
        "- id=%s | name=%s | beschreibung=%s | hub=%s"
        % (
            ziel.get("id"),
            ziel.get("name") or "",
            ziel.get("beschreibung") or "",
            ziel.get("hub") or "",
        )
        for ziel in ziele
    )
    user = (
        "Verfügbare Ziele:\n"
        + ziel_lines
        + "\n\nDokumenttext:\n"
        + text
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def classify(text, ziele):
    """Klassifiziert einen Dokumenttext und liefert ein dict mit den Feldern
    ziel_id, datum, absender, dokumenttyp, sicherheit.

    Bei ungültigem JSON wird genau einmal erneut versucht. Schlägt auch der
    zweite Versuch fehl, wird ValueError geworfen.
    """
    text = (text or "").strip()[:MAX_TEXT_CHARS]
    messages = _build_messages(text, ziele)

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
