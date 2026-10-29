"""Language identification + translation, honestly labelled.

- Identification: script detection (features/language.py) plus a
  stopword heuristic for major Latin-script languages (English,
  Spanish, French, German, Portuguese, Italian, Dutch). This is a
  heuristic, not a language claim — it is labelled as such, and the
  original text is always preserved.
- Translation: if an LLM key is configured, AILayer.translate is
  used; otherwise the free MyMemory public API is tried once per
  text (single GET, no key, rate-limited service — a failure is
  degraded, never a fabricated translation). Machine translation
  is always flagged: MT alone never carries a consequential finding,
  and the original text stays beside it in evidence.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
import json

_STOPWORDS = {
    "english": {"the", "and", "you", "that", "have", "with", "this", "from", "they", "about"},
    "spanish": {"los", "las", "una", "con", "para", "que", "por", "est", "sus", "del"},
    "french": {"les", "des", "une", "pour", "que", "dans", "sur", "pas", "plus", "aux"},
    "german": {"die", "der", "und", "den", "von", "mit", "sich", "des", "ist", "für"},
    "portuguese": {"que", "para", "com", "uma", "dos", "não", "mais", "como", "são", "seu"},
    "italian": {"che", "di", "una", "per", "con", "sono", "del", "della", "nel", "gli"},
    "dutch": {"van", "het", "een", "dat", "zijn", "voor", "met", "aan", "door", "bij"},
}


def identify_language(text: str) -> dict:
    from .language import detect_language

    script = detect_language(text or "")
    words = set(re.findall(r"[a-zà-ÿ]+", (text or "").lower()))
    best, best_count = None, 0
    for lang, stops in _STOPWORDS.items():
        count = len(words & stops)
        if count > best_count:
            best, best_count = lang, count
    return {
        "script": script,
        "likely_language": best if best_count >= 2 else None,
        "heuristic": True,
        "note": "Stopword heuristic only; not a language-identification claim. Original text preserved.",
    }


def translate_text(text: str, target: str = "en", keys: dict | None = None) -> dict:
    """Translate one text; original preserved, MT flagged."""
    if not text:
        return {"original_text": "", "translated_text": None, "status": "not_checked", "engine": None}
    # LLM first, if a key is configured (AILayer handles no-key as not_checked).
    try:
        from personatrace.ai.layer import AILayer

        layer = AILayer(mode="llm", keys=keys or {})
        if layer.api_key:
            result = layer.translate(text, target)
            if result.get("status") == "ok":
                return {
                    "original_text": text, "translated_text": result.get("translated_text"),
                    "status": "ok", "engine": "llm", "machine_translation": True,
                    "note": "Machine translation — original preserved; MT alone never carries a consequential finding.",
                }
    except Exception:
        pass
    # Free MyMemory public API, one call.
    try:
        url = (
            "https://api.mymemory.translated.net/get?q=" + urllib.parse.quote(text[:500])
            + "&langpair=autodetect|" + urllib.parse.quote(target)
        )
        req = urllib.request.Request(url, headers={"User-Agent": "PersonaTrace/1.3 (translation lookup)"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        translated = (data.get("responseData") or {}).get("translatedText")
        if translated:
            return {
                "original_text": text, "translated_text": translated,
                "status": "ok", "engine": "mymemory", "machine_translation": True,
                "note": "Machine translation — original preserved; MT alone never carries a consequential finding.",
            }
    except Exception as exc:
        return {"original_text": text, "translated_text": None, "status": "degraded", "engine": None, "message": str(exc)}
    return {"original_text": text, "translated_text": None, "status": "not_checked", "engine": None}
