import unittest

from staticpages.manifest import Manifest, RESERVED, validate


class MediaPrefixTest(unittest.TestCase):
    def manifest(self, prefix):
        return Manifest("www.example.com", "zone", "origin.example.com", "pages",
                        [{"prefix": "/deck/", "status": "active"}], [],
                        {"prefix": prefix, "bucket": "media", "endpoint": "oss.example.com",
                         "region": "cn-hangzhou", "min_bytes": 20_000_000})

    def test_all_main_site_prefixes_are_reserved_for_media_too(self):
        for prefix in RESERVED:
            with self.subTest(prefix=prefix):
                self.assertIn(f"media.prefix {prefix!r}: reserved by the main site", validate(self.manifest(prefix)))

    def test_dedicated_prefix_is_valid(self):
        self.assertEqual(validate(self.manifest("/_media/")), [])

    def test_namespace_overlap_is_still_rejected(self):
        self.assertTrue(validate(self.manifest("/deck/")))


if __name__ == "__main__":
    unittest.main()
