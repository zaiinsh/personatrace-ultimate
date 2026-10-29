"""Manual place clue for a SINGLE public photo (analyst note only).

This is an analyst's own note about one public photo the analyst
already holds. It is NOT automatic person tracking: there is no
movement map, no live location, no coordinates, and no face data in
the output. Nothing here is geocoded, and nothing here follows a
person over time.
"""

__all__ = ["manual_place_clue"]


def manual_place_clue(photo_description: str, analyst_note: str, source_url: str) -> dict:
    """Record an analyst note about one public photo.

    ``photo_description`` describes what the analyst sees in the photo;
    ``analyst_note`` is the analyst's own observation. No coordinates
    are accepted or produced, and no face information is recorded.
    """
    return {
        "type": "manual_place_clue",
        "scope": "single public photo only",
        "photo_description": photo_description or "",
        "analyst_note": analyst_note or "",
        "source_url": source_url or "",
        "method": "manual_analyst_note",
        "coordinates": None,
        "face_data": None,
        "movement_map": None,
        "live_location": None,
        "disclaimer": (
            "Analyst note only. This is not automatic person tracking, "
            "not a movement map, and not live location. No face data "
            "is recorded or inferred."
        ),
    }
