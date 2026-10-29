"""OCR + image description for public images already held.

- Description (always, no key): size, mode, dominant colours
  (Pillow, when installed), pHash and format — a description of the
  image file, never a face or identity claim.
- OCR text (only when a real OCR path is configured):
  1. pytesseract + system tesseract, if installed, or
  2. a user-configured OCR API endpoint (env PERSONATRACE_OCR_URL
     + PERSONATRACE_OCR_KEY, POST image bytes, JSON with a "text"
     field expected).
  Otherwise OCR returns status="not_checked" with install/setup
  instructions — never invented text. OCR text, when present, is
  labelled machine-read and must be checked against the image.
"""

from __future__ import annotations

import io
import json
import os
import urllib.request
from collections import Counter


def describe_image(image_bytes: bytes) -> dict:
    """Describe an image file; OCR text is added only via a real OCR path."""
    result = {"size": None, "mode": None, "format": None, "dominant_colours": [], "phash": None, "ocr": {"status": "not_checked", "text": None}}
    try:
        from personatrace.features.phash import ahash, is_image_bytes

        if is_image_bytes(image_bytes):
            result["phash"] = ahash(image_bytes)
    except Exception:
        pass
    try:
        from PIL import Image

        with Image.open(io.BytesIO(image_bytes)) as im:
            result["size"] = list(im.size)
            result["mode"] = im.mode
            result["format"] = im.format
            small = im.convert("RGB").resize((16, 16))
            colours = Counter(small.getdata()).most_common(3)
            result["dominant_colours"] = [list(c[0]) for c in colours]
    except Exception as exc:
        result["image_error"] = str(exc)
    # OCR paths, in order.
    ocr_text = None
    try:
        import pytesseract
        from PIL import Image as _Image

        with _Image.open(io.BytesIO(image_bytes)) as im:
            ocr_text = pytesseract.image_to_string(im)
        if ocr_text is not None:
            result["ocr"] = {"status": "ok", "text": ocr_text.strip(), "engine": "tesseract"}
            return result
    except Exception:
        pass
    ocr_url = os.environ.get("PERSONATRACE_OCR_URL")
    if ocr_url:
        try:
            req = urllib.request.Request(
                ocr_url, data=image_bytes,
                headers={"Content-Type": "application/octet-stream",
                         "Authorization": f"Bearer {os.environ.get('PERSONATRACE_OCR_KEY', '')}"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
            text = data.get("text") or data.get("ocr") or ""
            result["ocr"] = {"status": "ok" if text else "degraded", "text": text, "engine": "configured_ocr_api"}
            return result
        except Exception as exc:
            result["ocr"] = {"status": "degraded", "text": None, "message": str(exc)}
            return result
    result["ocr"] = {
        "status": "not_checked", "text": None,
        "message": "Install tesseract + pytesseract, or set PERSONATRACE_OCR_URL (+ key), to enable OCR. Image description above does not include OCR text.",
    }
    return result
