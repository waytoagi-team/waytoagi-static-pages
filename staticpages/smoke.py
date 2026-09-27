"""Browser smoke test of dist/ at the final nested paths."""
import functools
import http.server
import threading
from urllib.parse import urlparse


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def _serve(directory):
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def run(out, mounts):
    from playwright.sync_api import sync_playwright

    server = _serve(out)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for m in mounts:
                errors += _check_mount(browser, base, m)
            browser.close()
    finally:
        server.shutdown()
    return errors


def _check_mount(browser, base, m):
    page = browser.new_page()
    problems, external = [], []

    def same_origin(url):
        return urlparse(url).netloc == urlparse(base).netloc

    page.on("pageerror", lambda e: problems.append(f"JS error: {e}"))
    def on_console(msg):
        # Resource load failures are classified by origin in on_response / on_failed instead.
        if msg.type == "error" and not msg.text.startswith("Failed to load resource"):
            problems.append(f"console error: {msg.text}")

    page.on("console", on_console)

    def on_response(resp):
        if resp.status >= 400:
            (problems if same_origin(resp.url) else external).append(f"{resp.status} {resp.url}")

    def on_failed(req):
        (problems if same_origin(req.url) else external).append(f"failed {req.url}")

    page.on("response", on_response)
    page.on("requestfailed", on_failed)

    page.goto(f"{base}{m.path}", wait_until="load")
    for step in m.smoke:
        if "fill" in step:
            page.fill(step["fill"]["selector"], step["fill"]["value"])
        exp = step.get("expect")
        if exp:
            try:
                page.wait_for_function(
                    "([s, n]) => document.querySelectorAll(s).length >= n",
                    arg=[exp["selector"], exp.get("min", 1)], timeout=15000,
                )
            except Exception:
                n = page.locator(exp["selector"]).count()
                problems.append(f"expected >= {exp.get('min', 1)} x {exp['selector']!r}, found {n} (step {step})")
    page.close()

    # Third-party resources (avatars, embeds) can be flaky in CI; report them, do not fail on them.
    for e in external[:10]:
        print(f"    note: external resource {e}")
    return [f"{m.path}: {p}" for p in problems]
