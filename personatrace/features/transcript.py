"""Video transcript fetch for public YouTube videos, honestly capped.

Attempts, in order, for one video id (single GET each, 10s timeout,
no retry):
1. YouTube timedtext track list (public caption endpoint). If it
   lists a track, the track is fetched and parsed to plain text.
2. If no track list / no captions are available, returns
   status="no_captions" — never a fabricated transcript, and never
   a transcript claimed from titles/descriptions (those stay in
   analysis as titles/descriptions, clearly labelled).

Captions are public content only when the uploader published them.
Private / auto-generated captions that are not listed are not
pursued further, and no login is used.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

_TIMEOUT = 10
_USER_AGENT = "Mozilla/5.0 (public caption lookup)"


def _get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as exc:
        return exc.code, "", f"HTTP {exc.code}"
    except Exception as exc:
        return None, "", str(exc)


def fetch_transcript(video_id: str, lang: str = "en") -> dict:
    """Fetch a public YouTube transcript, or report honestly why not."""
    if not video_id or not re.fullmatch(r"[\w-]{6,}", video_id or ""):
        return {"status": "invalid", "text": None, "video_id": video_id}
    code, body, err = _get(
        f"https://www.youtube.com/api/timedtext?v={urllib.parse.quote(video_id)}&type=list"
    )
    if code != 200 or not body.strip():
        return {"status": "degraded" if err else "no_captions", "text": None, "video_id": video_id, "message": err or "No caption track list returned for this video."}
    try:
        root = ET.fromstring(body)
        tracks = []
        for track in root.findall("track"):
            tracks.append((track.get("lang_code"), track.get("name")))
    except Exception:
        tracks = []
    if not tracks:
        return {"status": "no_captions", "text": None, "video_id": video_id, "message": "No caption tracks listed for this video."}
    chosen = lang if any(code_ == lang for code_, _ in tracks) else tracks[0][0]
    code, body, err = _get(
        f"https://www.youtube.com/api/timedtext?v={urllib.parse.quote(video_id)}&lang={urllib.parse.quote(chosen)}&fmt=json3"
    )
    if code != 200 or not body.strip():
        return {"status": "degraded", "text": None, "video_id": video_id, "message": err or f"HTTP {code}"}
    try:
        import json as _json

        data = _json.loads(body)
        parts = []
        for event in data.get("events", []):
            for seg in event.get("segs", []) or []:
                if seg.get("utf8"):
                    parts.append(seg["utf8"])
        text = re.sub(r"\s+", " ", " ".join(parts)).strip()
        return {"status": "ok" if text else "no_captions", "text": text or None, "video_id": video_id, "lang": chosen}
    except Exception:
        text = re.sub(r"<[^>]+>", " ", body)
        text = re.sub(r"\s+", " ", text).strip()
        return {"status": "ok" if text else "no_captions", "text": text or None, "video_id": video_id, "lang": chosen}
