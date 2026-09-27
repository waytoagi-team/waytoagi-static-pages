"""Exercise verification against a real HTTP server, including legacy Chinese filenames."""
import hashlib
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from staticpages.verify import verify_files


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


if __name__ == "__main__":
    unittest.main()
