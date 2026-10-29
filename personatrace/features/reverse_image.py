"""Reverse image search via official, key-gated engines — plus local pHash.

Engines (only when the investigator supplies a key; otherwise
not_checked, never a fabricated match):
- TinEye API: POST/GET to https://api.tineye.com/rest/search/ with
  image_url + api_key (TinEye's official API). Returns matches with
  backlinks when the image is already indexed by TinEye.
- Bing Visual Search: POST https://api.bing.microsoft.com/v7.0/images/visualsearch
  with Ocp-Apim-Subscription-Key and the image bytes (multipart).
  Returns visually similar pages when Azure returns them.

Local pHash (features/phash.py) is always available and is the
fallback: it only finds reuse among images already held, it does
not search the web. A web engine miss is inconclusive — different
engines index different corpora, as the blueprint notes.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid

_TIMEOUT = 10
_USER_AGENT = "PersonaTrace/1.3 (reverse-image lookup)"


def _tineye(image_url: str, key: str) -> dict:
    url = (
        "https://api.tineye.com/rest/search/?api_key=" + urllib.parse.quote(key)
        + "&image_url=" + urllib.parse.quote(image_url)
    )
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        return {"engine": "tineye", "status": "degraded", "message": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"engine": "tineye", "status": "degraded", "message": str(exc)}
    matches = []
    for result in (data.get("results") or {}).get("matches", []) or []:
        for backlink in result.get("backlinks", []) or []:
            matches.append({"url": backlink.get("url"), "domain": backlink.get("domain")})
    return {"engine": "tineye", "status": "ok", "matches": matches[:20], "total": data.get("results", {}).get("total_results")}


def _bing(image_bytes: bytes, key: str) -> dict:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"image.jpg\"\r\n"
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode() + image_bytes + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        "https://api.bing.microsoft.com/v7.0/images/visualsearch",
        data=body,
        headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        return {"engine": "bing_visual_search", "status": "degraded", "message": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"engine": "bing_visual_search", "status": "degraded", "message": str(exc)}
    matches = []
    for tag in (data.get("tags") or []):
        for action in tag.get("actions", []) or []:
            for item in action.get("data", {}).get("value", []) or []:
                if item.get("contentUrl"):
                    matches.append({"url": item["contentUrl"], "name": item.get("name")})
    return {"engine": "bing_visual_search", "status": "ok", "matches": matches[:20]}


def reverse_search(image_url: str | None = None, image_bytes: bytes | None = None, keys: dict | None = None) -> dict:
    """Run configured reverse engines; unconfigured engines are not_checked."""
    keys = dict(keys or {})
    tineye_key = keys.get("tineye_api_key") or os.environ.get("TINEYE_API_KEY")
    bing_key = keys.get("bing_visual_search_key") or os.environ.get("BING_VISUAL_SEARCH_KEY")
    results = []
    if tineye_key and image_url:
        results.append(_tineye(image_url, tineye_key))
    elif not tineye_key:
        results.append({"engine": "tineye", "status": "not_checked", "message": "No TinEye API key configured."})
    if bing_key and image_bytes:
        results.append(_bing(image_bytes, bing_key))
    elif not bing_key:
        results.append({"engine": "bing_visual_search", "status": "not_checked", "message": "No Bing Visual Search key configured."})
    return {"engines": results, "note": "A miss on one engine is inconclusive; engines index different corpora."}
