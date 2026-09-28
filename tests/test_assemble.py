import json
import unittest
from types import SimpleNamespace

from staticpages.assemble import edgeone_config, middleware_source


class RedirectConfigTest(unittest.TestCase):
    manifest = SimpleNamespace(mounts=[
        SimpleNamespace(path="/usecase-atlas/opus5-5/"),
        SimpleNamespace(path="/deck/"),
    ])

    def test_static_config_does_not_generate_lossy_trailing_slash_redirects(self):
        offload = {"source": "/deck/video.mp4", "destination": "/_media/video.mp4", "statusCode": 302}

        self.assertEqual(edgeone_config(self.manifest, [offload])["redirects"], [offload])

    def test_middleware_redirect_uses_the_request_url_so_query_is_retained(self):
        source = middleware_source(self.manifest)

        self.assertIn('new Set(["/usecase-atlas/opus5-5", "/deck"])', source)
        self.assertIn('const url = new URL(request.url);', source)
        self.assertIn('url.pathname += "/";', source)
        self.assertIn('redirect(url.toString(), 308)', source)
        self.assertEqual(
            json.loads(source.split("export const config = { matcher: ", 1)[1].split(" }", 1)[0]),
            ["/usecase-atlas/opus5-5", "/deck"],
        )


if __name__ == "__main__":
    unittest.main()
