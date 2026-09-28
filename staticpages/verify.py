"""Compare what is served (origin / www) against dist/, and diff dist/ against the live origin."""
import hashlib
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode, urljoin, urlsplit

from .assemble import STATE_PATH

UA = "waytoagi-static-pages-verify/1"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def get(url, follow=True):
    opener = urllib.request.build_opener() if follow else urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    try:
        with opener.open(req, timeout=60) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        # TLS / DNS / connection errors (e.g. a new certificate still propagating): report, let callers retry.
        return f"error: {getattr(e, 'reason', e)}", None, b""


def live_state(origin_url, attempts=4):
    """The state manifest the origin serves now. 404 = nothing deployed yet. Any other failure is reported and
    treated as "everything changed", which is safe (redeploy + purge) but should not happen silently."""
    for i in range(attempts):
        status, _, body = get(f"{origin_url}/{STATE_PATH}?t={int(time.time())}")
        if status == 200:
            try:
                return json.loads(body)
            except ValueError:
                status = f"200 but not JSON ({body[:80]!r})"
        elif status == 404:
            print(f"live state: {origin_url}/{STATE_PATH} not found (first deploy)")
            return {"mounts": {}}
        if i + 1 < attempts:
            time.sleep(5 * (i + 1))
    print(f"warning: cannot read live state from {origin_url}/{STATE_PATH} ({status}); treating all mounts as changed")
    return {"mounts": {}}


def diff(state, live):
    """Mount paths whose content differs from what the origin currently serves."""
    new, old = state["mounts"], live.get("mounts", {})
    config_changed = live.get("deployment_config") != state.get("deployment_config")
    changed = sorted(p for p in new if config_changed or old.get(p, {}).get("tree") != new[p]["tree"])
    removed = sorted(p for p in old if p not in new)
    return {"changed": changed, "removed": removed}


def _check(url, expected, attempts=1):
    # Right after a deploy some edge nodes still serve the previous version (seen as brief 404s).
    for i in range(attempts):
        status, _, body = get(url)
        actual = hashlib.sha256(body).hexdigest() if status == 200 else None
        if actual == expected:
            return None
        if i + 1 < attempts:
            time.sleep(5 * (i + 1))
    return f"{url}: status {status}, sha256 {actual} != {expected}"


def verify_files(base_url, state, paths, bust):
    """Every file of the given mounts must be byte-identical to dist/."""
    jobs = []
    query = urlencode({"v": bust})
    for path in paths:
        files = state["mounts"][path]["files"]
        jobs.append((f"{base_url}{quote(path)}?{query}", files["index.html"]))
        # Encode filesystem names before constructing URLs: Chinese characters, spaces,
        # and literal # / ? / % are valid filenames, not URL syntax.
        jobs += [(f"{base_url}{quote(path + rel)}?{query}", h) for rel, h in files.items()]
    with ThreadPoolExecutor(8) as pool:
        return [e for e in pool.map(lambda j: _check(*j, attempts=5), jobs) if e]


def verify_prod(host, state, paths, attempts=6):
    """The public URL serves the new index.html; the bare path 308s without losing its query string."""
    errors = []
    for path in paths:
        expected = state["mounts"][path]["files"]["index.html"]
        err = _check(f"https://{host}{path}", expected, attempts=attempts)
        if err:
            errors.append(err)
        bare = f"https://{host}{path.rstrip('/')}?probe=1"
        status, headers, _ = get(bare, follow=False)
        loc = headers.get("Location", "") if headers else ""
        target = urlsplit(urljoin(bare, loc))
        expected = urlsplit(f"https://{host}{path}?probe=1")
        if status != 308 or target != expected:
            errors.append(f"{bare}: expected 308 to {expected.geturl()}, got {status} {loc!r}")
    return errors


def verify_offloaded(base_url, host, state, paths):
    """Offloaded files: the mount path 302s to https://<host>/<key> (checked on base_url, origin or www), and www serves
    the object with the right size. Content was hashed at upload (x-oss-meta-sha256)."""
    errors = []
    for path in paths:
        for rel, e in state["mounts"][path].get("offloaded", {}).items():
            url = f"{base_url}{quote(path + rel)}"
            for i in range(5):
                status, headers, _ = get(url, follow=False)
                loc = (headers.get("Location", "") if headers else "").split("?")[0]
                if status == 302 and loc == f"https://{host}/{e['key']}":
                    break
                time.sleep(5 * (i + 1))
            else:
                errors.append(f"{url}: expected 302 to https://{host}/{e['key']}, got {status} {loc!r}")
            media = f"https://{host}/{e['key']}"
            req = urllib.request.Request(media, method="HEAD", headers={"User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    size = int(resp.headers.get("Content-Length", -1))
                    if size != e["size"]:
                        errors.append(f"{media}: size {size} != {e['size']}")
            except Exception as ex:
                errors.append(f"{media}: {ex}")
    return errors


REGRESSION_PATHS = ("/", "/zh", "/events")


def regression(host):
    """Main-site pages must keep working and must not be served by this origin."""
    errors = []
    for p in REGRESSION_PATHS:
        status, _, body = get(f"https://{host}{p}")
        if status != 200:
            errors.append(f"https://{host}{p}: status {status}")
        elif b"WaytoAGI static pages origin" in body:
            errors.append(f"https://{host}{p}: served by the static-pages origin")
    return errors
