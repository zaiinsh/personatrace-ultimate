"""Tests for personatrace.features (stdlib + unittest only, no network).

Run with pytest if available, else: python3 -m unittest discover -s tests -t .
"""

import struct
import unittest

from personatrace.features import (
    alerts,
    archive,
    biolink,
    coordinated,
    export,
    infra_location,
    language,
    manual,
    phash,
    phrase,
    stylometry,
)
from demo.fixtures import demo_investigation


def make_bmp(width, height, pixel_fn):
    """Minimal 24-bit BMP (bottom-up) with pixel_fn(x, y) -> (r, g, b)."""
    row = width * 3
    pad = (4 - row % 4) % 4
    pixels = bytearray()
    for y in range(height - 1, -1, -1):
        for x in range(width):
            r, g, b = pixel_fn(x, y)
            pixels += bytes([b, g, r])
        pixels += b"\x00" * pad
    header_size, offset = 40, 54
    file_size = offset + len(pixels)
    header = b"BM" + struct.pack("<IHHI", file_size, 0, 0, offset)
    dib = struct.pack("<IiiHHIIiiII", header_size, width, height, 1, 24, 0,
                      len(pixels), 2835, 2835, 0, 0)
    return header + dib + bytes(pixels)


WHITE = lambda x, y: (255, 255, 255)  # noqa: E731
BLACK = lambda x, y: (0, 0, 0)  # noqa: E731


class TestPhash(unittest.TestCase):
    def test_identical_bytes_match(self):
        img = make_bmp(16, 16, lambda x, y: (255, 255, 255) if x < 8 else (0, 0, 0))
        self.assertEqual(phash.ahash(img), phash.ahash(img))
        self.assertTrue(phash.is_reuse(phash.ahash(img), phash.ahash(img)))
        self.assertTrue(phash.is_reuse_bytes(img, img))

    def test_different_bytes_distance_large(self):
        a = make_bmp(16, 16, WHITE)
        # Left half white, right half black: 8x8 reduction gives 32 ones
        # and 32 zeros, vs 64 ones for uniform white -> distance 32.
        # (A fine checkerboard is NOT a good test image: block-averaging
        # collapses it to uniform grey, which correctly hashes identically.)
        b = make_bmp(16, 16, lambda x, y: (255, 255, 255) if x < 8 else (0, 0, 0))
        dist = phash.hamming(phash.ahash(a), phash.ahash(b))
        self.assertGreaterEqual(dist, 20)

    def test_threshold_behaviour(self):
        self.assertTrue(phash.is_reuse(0, 0b1111111111, threshold=10))
        self.assertFalse(phash.is_reuse(0, 0b11111111111, threshold=10))
        self.assertTrue(phash.is_reuse(0, 0b11111111111, threshold=11))

    def test_non_image_never_claimed_as_reuse(self):
        self.assertFalse(phash.is_image_bytes(b"not an image at all"))
        self.assertFalse(phash.is_reuse_bytes(b"not an image", b"not an image"))
        self.assertTrue(phash.is_image_bytes(make_bmp(8, 8, WHITE)))


class TestArchive(unittest.TestCase):
    def test_diff_only_changed_fields(self):
        inv = demo_investigation()
        old, new = inv.profiles[0], inv.profiles[0]
        import copy
        changed = copy.copy(new)
        changed.bio = "Changed demo bio."
        diff = archive.diff_snapshots(old, changed)
        self.assertEqual(set(diff), {"bio"})
        self.assertEqual(diff["bio"]["new"], "Changed demo bio.")
        self.assertEqual(archive.diff_snapshots(old, old), {})

    def test_snapshot_fields(self):
        snap = archive.snapshot(demo_investigation().profiles[0])
        self.assertEqual(snap["username"], "demo_user_01")
        self.assertIn("bio_links", snap)


class TestBiolink(unittest.TestCase):
    def test_extract_domains(self):
        domains = biolink.extract_domains(
            ["https://www.example.com/blog", "http://sub.example.org:8080/x"],
            "find me at demo-site.example.net and me@example.com",
        )
        self.assertEqual(domains, ["example.com", "sub.example.org", "demo-site.example.net"])

    def test_expand_domain_no_network_placeholder(self):
        result = biolink.expand_domain("example.com")
        self.assertEqual(result["method"], "public_lookup")
        self.assertEqual(result["ct_log"], "not_checked")
        self.assertEqual(result["dns"], "not_checked")


class TestCoordinated(unittest.TestCase):
    def _accounts(self):
        return [
            {"created_at": "2024-01-01T00:00:00Z", "bio": "Demo team alpha research",
             "posts": [{"created_at": "2024-02-01T10:00:00Z", "text": "hello world post one"}]},
            {"created_at": "2024-01-03T00:00:00Z", "bio": "Demo team alpha research",
             "posts": [{"created_at": "2024-02-02T10:00:00Z", "text": "hello world post two"}]},
        ]

    def test_verdict_and_innocent_explanations(self):
        result = coordinated.crowd_check(self._accounts())
        self.assertEqual(result["verdict"], "pattern, not proof")
        self.assertTrue(result["innocent_explanations"])
        self.assertTrue(result["signals"])

    def test_never_labels_account_bot(self):
        result = coordinated.crowd_check(self._accounts())
        self.assertNotIn("bot", str(result).lower())


class TestLanguage(unittest.TestCase):
    def test_scripts(self):
        self.assertEqual(language.detect_language("Hello world, this is English text"), "latin")
        self.assertEqual(language.detect_language("Привет мир, это русский текст"), "cyrillic")
        self.assertEqual(language.detect_language("مرحبا بالعالم هذا نص عربي"), "arabic")
        self.assertEqual(language.detect_language("你好世界这是一个中文文本"), "cjk")
        self.assertEqual(language.detect_language(""), "other")

    def test_original_preserved(self):
        text = "مرحبا بالعالم"
        detailed = language.detect_language_detailed(text)
        self.assertEqual(detailed["original_text"], text)


class TestStylometry(unittest.TestCase):
    def test_warns_below_500_words_and_flagged_weak(self):
        result = stylometry.style_similarity("the cat sat on the mat", "the dog sat on the rug")
        self.assertTrue(result["weak_signal"])
        self.assertIsNotNone(result["warning"])
        self.assertLess(result["sample_words_a"], 500)

    def test_no_warning_at_500_words(self):
        text = " ".join(["the quick brown fox jumps over the lazy dog"] * 60)  # 540 words
        result = stylometry.style_similarity(text, text)
        self.assertIsNone(result["warning"])
        self.assertAlmostEqual(result["score"], 1.0, places=3)

    def test_timing_similarity(self):
        self.assertAlmostEqual(stylometry.timing_similarity([10, 10, 11], [10, 10, 11]), 1.0, places=3)
        self.assertEqual(stylometry.timing_similarity([10], [22]), 0.0)


class TestAlerts(unittest.TestCase):
    def test_only_new_edges_alert(self):
        old = [{"from_id": "a", "to_id": "b", "kind": "same_username"}]
        new = old + [{"from_id": "a", "to_id": "c", "kind": "bio_link"}]
        result = alerts.check_new_edges(old, new)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["edge_kind"], "bio_link")
        self.assertEqual(alerts.check_new_edges(new, new), [])
        self.assertEqual(alerts.check_new_edges(new, old), [])


class TestPhrase(unittest.TestCase):
    def test_exact_phrase_match_with_source(self):
        corpus = [
            {"text": "I love demo security research daily", "source_url": "https://example.invalid/1",
             "platform": "github", "username": "demo_user_01"},
            {"text": "unrelated demo text", "source_url": "https://example.invalid/2"},
        ]
        matches = phrase.search_phrase(corpus, "demo security research")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["source_url"], "https://example.invalid/1")
        self.assertEqual(phrase.search_phrase(corpus, "absent phrase"), [])
        self.assertEqual(phrase.search_phrase(corpus, ""), [])


class TestManualAndInfra(unittest.TestCase):
    def test_manual_place_clue_no_tracking_fields(self):
        clue = manual.manual_place_clue("A public photo of a demo landmark",
                                        "Analyst notes demo landmark visible",
                                        "https://example.invalid/photo")
        self.assertIsNone(clue["coordinates"])
        self.assertIsNone(clue["face_data"])
        self.assertIsNone(clue["movement_map"])
        self.assertIsNone(clue["live_location"])

    def test_infra_location_server_only(self):
        result = infra_location.infrastructure_location("example.com")
        self.assertEqual(result["method"], "public_lookup")
        self.assertEqual(result["scope"], "server_or_domain_infrastructure_only")
        self.assertEqual(result["country"], "not_checked")


class TestExport(unittest.TestCase):
    def test_html_and_json_contain_provenance_for_every_fact(self):
        import tempfile
        inv = demo_investigation()
        with tempfile.TemporaryDirectory() as tmp:
            html_path = export.export_case(inv, tmp, fmt="html")
            json_path = export.export_case(inv, tmp, fmt="json")
            with open(html_path, encoding="utf-8") as f:
                html_text = f.read()
            with open(json_path, encoding="utf-8") as f:
                data = __import__("json").loads(f.read())
        facts = [ev for p in inv.profiles for ev in p.evidence]
        self.assertTrue(facts)
        for ev in facts:
            for needle in (ev.source_url, ev.captured_at_utc, ev.method, str(ev.confidence)):
                self.assertIn(needle, html_text)
        self.assertEqual(len(data["provenance"]), len(facts))
        for fact in data["provenance"]:
            for key in ("source_url", "captured_at_utc", "method", "confidence"):
                self.assertIn(key, fact)
        self.assertTrue(data["audit"])
        self.assertEqual(data["single_case_only"], True)
        with self.assertRaises(ValueError):
            export.export_case(inv, tmp, fmt="xml")
        # v1.4: CSV export is supported and carries provenance.
        csv_path = export.export_case(inv, tmp, fmt="csv")
        self.assertTrue(csv_path.endswith("case.csv"))


class TestDemoFixtures(unittest.TestCase):
    def test_demo_shape(self):
        inv = demo_investigation()
        self.assertEqual(inv.seed, "demo_user_01")
        self.assertGreaterEqual(len(inv.profiles), 6)
        self.assertGreaterEqual(len({p.platform for p in inv.profiles}), 4)
        self.assertGreaterEqual(len(inv.edges), 8)
        self.assertTrue(all(p.username.startswith("demo_") for p in inv.profiles))
        self.assertTrue(any(e.from_id.endswith("demo_bridge_01") or e.to_id.endswith("demo_bridge_01")
                            for e in inv.edges))
        self.assertTrue(inv.timeline and inv.alerts and inv.audit)
        self.assertEqual(inv.possible_matches[0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
