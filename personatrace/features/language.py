"""Script-based language-script detection (stdlib only).

Returns a script family, not a language identification claim:
"latin" | "cyrillic" | "arabic" | "cjk" | "devanagari" | "thai" | "other".
The original text is always preserved alongside any result; this
module performs no translation and never discards the original.
"""

__all__ = ["detect_language", "detect_language_detailed"]

_RANGES = (
    ("cyrillic", ((0x0400, 0x04FF), (0x0500, 0x052F))),
    ("arabic", ((0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF))),
    ("devanagari", ((0x0900, 0x097F), (0xA8E0, 0xA8FF))),
    ("thai", ((0x0E00, 0x0E7F),)),
    ("cjk", ((0x4E00, 0x9FFF), (0x3040, 0x30FF), (0xAC00, 0xD7AF))),
    ("latin", ((0x0041, 0x005A), (0x0061, 0x007A), (0x00C0, 0x024F))),
)


def _script_of(char: str) -> str | None:
    code = ord(char)
    for name, ranges in _RANGES:
        for low, high in ranges:
            if low <= code <= high:
                return name
    return None


def detect_language(text: str) -> str:
    """Return the dominant script family of *text*, or "other"."""
    counts = {}
    for char in text or "":
        script = _script_of(char)
        if script:
            counts[script] = counts.get(script, 0) + 1
    if not counts:
        return "other"
    return max(counts.items(), key=lambda item: item[1])[0]


def detect_language_detailed(text: str) -> dict:
    """Detection result with the original text preserved verbatim."""
    return {
        "detected_script": detect_language(text),
        "original_text": text or "",
        "translation": None,
        "translation_note": (
            "No translation performed; original text preserved alongside "
            "any future translation placeholder."
        ),
    }
