"""Exercise verification against a real HTTP server, including legacy Chinese filenames."""
import hashlib
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from staticpages.verify import diff, verify_files, verify_prod


class VerifyFilesTest(unittest.TestCase):
    def test_unicode_and_reserved_filename_characters(self):
        requests = []

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                requests.append(self.path)
                super().do_GET()

            def log_message(self, *args):
                pass

        files = {
            "index.html": b"home",
            "WaytoAGI-社区介绍-10页.html": "社区介绍".encode(),
            "images/a b#c?d%20.png": b"image",
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, data in files.items():
                p = Path(tmp) / "kemengopc" / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(data)
            state = {"mounts": {"/kemengopc/": {"files": {
                name: hashlib.sha256(data).hexdigest() for name, data in files.items()
            }}}}
            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=tmp))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                errors = verify_files(f"http://127.0.0.1:{server.server_port}", state,
                                      ["/kemengopc/"], bust="deploy #1&x=2")
                self.assertEqual(errors, [])
                self.assertEqual(len(requests), len(files) + 1)
                self.assertTrue(all(parse_qs(urlsplit(p).query) == {"v": ["deploy #1&x=2"]}
                                    for p in requests))
            finally:
                server.shutdown()
                server.server_close()
                thread.join()


class VerifyProdTest(unittest.TestCase):
    state = {"mounts": {"/deck/": {"files": {"index.html": "hash"}}}}

    @patch("staticpages.verify._check", return_value=None)
    @patch("staticpages.verify.get")
    def test_trailing_slash_redirect_preserves_probe_query(self, get, _check):
        get.return_value = 308, {"Location": "/deck/?probe=1"}, b""

        self.assertEqual(verify_prod("www.example.com", self.state, ["/deck/"], attempts=1), [])
        get.assert_called_once_with("https://www.example.com/deck?probe=1", follow=False)

    @patch("staticpages.verify._check", return_value=None)
    @patch("staticpages.verify.get")
    def test_trailing_slash_redirect_rejects_lost_query(self, get, _check):
        get.return_value = 308, {"Location": "/deck/"}, b""

        errors = verify_prod("www.example.com", self.state, ["/deck/"], attempts=1)

        self.assertEqual(len(errors), 1)
        self.assertIn("expected 308 to https://www.example.com/deck/?probe=1", errors[0])


class DiffTest(unittest.TestCase):
    def test_deployment_config_change_marks_all_mounts_changed(self):
        mounts = {
            "/a/": {"tree": "same"},
            "/b/": {"tree": "same"},
        }
        state = {"deployment_config": "new", "mounts": mounts}
        live = {"deployment_config": "old", "mounts": mounts}

        self.assertEqual(diff(state, live), {"changed": ["/a/", "/b/"], "removed": []})

    def test_matching_deployment_config_keeps_unchanged_mounts_unchanged(self):
        mounts = {"/a/": {"tree": "same"}}
        state = {"deployment_config": "same", "mounts": mounts}

        self.assertEqual(diff(state, state), {"changed": [], "removed": []})


if __name__ == "__main__":
    unittest.main()
