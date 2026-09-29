"""Publishing checks must cover OSS candidates as well as Pages files."""
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from staticpages import __main__ as pipeline, assemble, checks
from staticpages.manifest import Manifest, Mount


class PublishChecksTest(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.out = Path(work.name) / "dist"
        self.cache = Path(work.name) / "media"
        self.manifest = Manifest("www.example.com", "zone", "origin.example.com", "pages",
                                 [{"prefix": "/deck/", "status": "active"}],
                                 [Mount("/deck/", "owner", {"inline": "fixture"})],
                                 {"prefix": "/_media/", "min_bytes": 20_000_000, "always": ["*.mp4"]})
        for target, value in (("staticpages.assemble.MEDIA_CACHE", self.cache),
                              ("staticpages.checks.MEDIA_CACHE", self.cache),
                              ("staticpages.__main__.DIST", self.out)):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def build(self, files):
        with patch.object(assemble, "read_inline", return_value={"index.html": b"home", **files}):
            return pipeline.build(self.manifest)

    def test_large_javascript_with_secret_fails_before_upload(self):
        marker = b"-----BEGIN PRIVATE KEY-----"
        data = b" " * (20_000_000 - len(marker)) + marker
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            self.build({"large-bundle.js": data})
        self.assertFalse((self.out / "deck/large-bundle.js").exists())
        self.assertIn("/deck/large-bundle.js: looks like it contains a Private key", output.getvalue())
        self.assertNotIn(marker.decode(), output.getvalue())

    def test_small_always_offloaded_file_is_also_scanned(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            self.build({"clip.mp4": b"-----BEGIN PRIVATE KEY-----"})

    def test_size_limit_applies_only_to_pages(self):
        with patch.object(checks, "MAX_FILE_BYTES", 32), contextlib.redirect_stdout(io.StringIO()):
            state = self.build({"clip.mp4": b"x" * 64})
            self.assertIn("clip.mp4", state["mounts"]["/deck/"]["offloaded"])
            with self.assertRaises(SystemExit):
                self.build({"index.html": b"x" * 64})

    def test_oversized_index_html_is_rejected_with_split_hint(self):
        self.manifest.media["min_bytes"] = 64
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            self.build({"index.html": b"<p>" + b"x" * 100})
        self.assertIn("/deck/index.html: 103 bytes; .html files cannot be offloaded", output.getvalue())
        self.assertIn("Split it: move embedded data", output.getvalue())

    def test_large_secondary_page_and_css_stay_on_pages_and_are_rejected(self):
        self.manifest.media["min_bytes"] = 64
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            self.build({"指南.html": b"x" * 100, "site.css": b"x" * 100})
        self.assertTrue((self.out / "deck/指南.html").exists())  # not offloaded behind a 302
        self.assertIn("/deck/指南.html: 100 bytes; .html files cannot be offloaded", output.getvalue())
        self.assertIn("/deck/site.css: 100 bytes; .css files cannot be offloaded", output.getvalue())
        self.assertIn("relative url()", output.getvalue())

    def test_html_just_under_threshold_passes(self):
        self.manifest.media["min_bytes"] = 64
        with contextlib.redirect_stdout(io.StringIO()):
            state = self.build({"index.html": b"x" * 63})
        self.assertNotIn("offloaded", state["mounts"]["/deck/"])

    def assertBuildFails(self, files, *expected):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            self.build(files)
        for text in expected:
            self.assertIn(text, output.getvalue())
        return output.getvalue()

    def test_copied_page_without_its_assets_fails(self):
        page = b'<img src="assets/a.png"><link rel="stylesheet" href="assets/site.css">'
        self.assertBuildFails(
            {"index.html": page, "assets/a.png": b"png", "assets/site.css": b"",
             "copy/index.html": page},
            "/deck/copy/index.html: reference 'assets/a.png' points to /deck/copy/assets/a.png, which is not published",
            "/deck/copy/index.html: reference 'assets/site.css' points to /deck/copy/assets/site.css")

    def test_valid_references_pass(self):
        page = ('<a href="#top">x</a><a href="guide/">g</a><a href="guide">g2</a>'
                '<img src="img/%E5%9B%BE.png?v=2#x" srcset="img/%E5%9B%BE.png 1x, img/big.png 2x">'
                '<video poster="img/big.png" src="clip.mp4"></video>'
                '<a href="https://example.com/a">e</a><a href="mailto:a@b.c">m</a><img src="data:image/png;base64,AA">'
                '<a href="//cdn.example.com/x.js">p</a><a href="/deck/guide/">abs</a>'
                '<a href="${item.url}">tpl</a><div style="background:url(img/big.png)"></div>'
                '<style>.x{background:url("img/%E5%9B%BE.png")}</style>').encode()
        with contextlib.redirect_stdout(io.StringIO()):
            state = self.build({"index.html": page, "guide/index.html": b"<a href='../index.html'>up</a>",
                                "img/图.png": b"png", "img/big.png": b"png", "clip.mp4": b"offloaded"})
        self.assertIn("clip.mp4", state["mounts"]["/deck/"]["offloaded"])  # offloaded targets count as published

    def test_reference_leaving_the_mount_fails(self):
        self.assertBuildFails({"index.html": b'<a href="../other/">x</a>'},
                              "/deck/index.html: reference '../other/' leaves /deck/")

    def test_missing_css_url_and_import_fail(self):
        self.assertBuildFails({"index.html": b'<link rel="stylesheet" href="s.css">',
                               "s.css": b'@import "base.css"; .a{background:url(font.woff2)}'},
                              "/deck/s.css: reference 'base.css' points to /deck/base.css",
                              "/deck/s.css: reference 'font.woff2' points to /deck/font.woff2")

    def test_allow_missing_skips_matching_targets(self):
        self.manifest.mounts[0].allow_missing = ["generated/*"]
        with contextlib.redirect_stdout(io.StringIO()):
            self.build({"index.html": b'<script src="generated/app.js"></script>'})

    def test_many_missing_references_are_summarised_per_file(self):
        page = "".join(f'<img src="m/{i}.png">' for i in range(8)).encode()
        out = self.assertBuildFails({"index.html": page}, "/deck/index.html: ... and 3 more missing references")
        self.assertEqual(out.count("which is not published"), 5)

    def test_scans_actual_cached_upload_bytes(self):
        with contextlib.redirect_stdout(io.StringIO()):
            state = self.build({"clip.mp4": b"clean media"})
        entry = state["mounts"]["/deck/"]["offloaded"]["clip.mp4"]
        (self.cache / entry["key"].rsplit("/", 1)[-1]).write_bytes(b"-----BEGIN PRIVATE KEY-----")
        self.assertTrue(any("Private key" in e for e in checks.run(self.manifest, self.out, state)))

    def test_gitleaks_includes_current_media_and_propagates_detection(self):
        with contextlib.redirect_stdout(io.StringIO()):
            state = self.build({"clip.mp4": b"clean media", "duplicate.mp4": b"clean media"})
        # A prior build's cache entry is not a candidate for publication.
        (self.cache / "stale.js").write_bytes(b"old content")
        current = next(checks.offloaded_files(state))[2]
        calls = []

        def scanner(argv, **kwargs):
            calls.append(Path(argv[2]))
            self.assertTrue(kwargs["check"])
            self.assertIn("--redact", argv)
            self.assertEqual(argv[argv.index("--max-target-megabytes") + 1], "0")
            if Path(argv[2]) == current:
                raise subprocess.CalledProcessError(1, argv)

        with patch.object(checks.subprocess, "run", side_effect=scanner), \
                self.assertRaises(subprocess.CalledProcessError):
            checks.scan_secrets(self.out)
        self.assertEqual(calls, [self.out, current])
        # The scanner obtains its candidates from the build that is about to deploy.
        self.assertEqual(json.loads((self.out / assemble.STATE_PATH).read_text()), state)


if __name__ == "__main__":
    unittest.main()
