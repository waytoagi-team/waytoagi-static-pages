"""Build dist/ from mounts.yaml: fetch each source at its pinned SHA, copy into its mount dir."""
import base64
import fnmatch
import hashlib
import io
import json
import mimetypes
import os
import shutil
import subprocess
import tarfile

from .manifest import ROOT

CACHE = ROOT / ".cache" / "sources"
MEDIA_CACHE = ROOT / ".cache" / "media"  # offloaded files, by key basename: smoke test + upload read them here
STATE_PATH = "_static-pages/manifest.json"  # published on the origin, used to diff the next deploy


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True).stdout


def auth_args():
    """Private source repos: read-only token from SOURCE_GITHUB_TOKEN (CI secret; locally `gh auth token`)."""
    token = os.environ.get("SOURCE_GITHUB_TOKEN")
    if not token:
        return []
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.https://github.com/.extraheader=Authorization: Basic {basic}"]


def fetch_tree(repo, ref, subdir):
    """Return {relpath: bytes} for repo@ref:subdir. Shallow-fetches exactly one commit."""
    cache = CACHE / repo.replace("/", "__")
    if not (cache / ".git").exists():
        cache.mkdir(parents=True, exist_ok=True)
        git("init", "-q", cwd=cache)
        git("remote", "add", "origin", f"https://github.com/{repo}.git", cwd=cache)
    try:
        git("cat-file", "-e", f"{ref}^{{commit}}", cwd=cache)
    except subprocess.CalledProcessError:
        try:
            git(*auth_args(), "fetch", "-q", "--depth", "1", "origin", ref, cwd=cache)
        except subprocess.CalledProcessError as e:
            hint = "" if os.environ.get("SOURCE_GITHUB_TOKEN") else " (private repo? set SOURCE_GITHUB_TOKEN)"
            raise SystemExit(f"cannot fetch {repo}@{ref}{hint}: {e.stderr.decode(errors='replace').strip()}")
    archive = git("archive", "--format=tar", f"{ref}:{subdir}", cwd=cache)
    files = {}
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            if member.isfile():
                files[member.name.removeprefix("./")] = tar.extractfile(member).read()
    if not files:
        raise SystemExit(f"{repo}@{ref}:{subdir} is empty or missing")
    return files


def read_inline(rel_dir):
    base = ROOT / rel_dir
    return {str(p.relative_to(base)): p.read_bytes() for p in sorted(base.rglob("*")) if p.is_file()}


def excluded(rel, patterns):
    if any(part.startswith(".") for part in rel.split("/")):
        return True
    return any(rel.startswith(p) if p.endswith("/") else fnmatch.fnmatch(rel, p) for p in patterns)


def offload(manifest, rel, data):
    """Files too large for EdgeOne Pages, or matching media.always, go to OSS instead of dist/."""
    md = manifest.media
    if not md:
        return False
    return len(data) >= md["min_bytes"] or any(fnmatch.fnmatch(rel.lower(), p) for p in md.get("always", []))


def media_key(manifest, data, rel):
    ext = os.path.splitext(rel)[1].lower()
    return f"{manifest.media['prefix'].lstrip('/')}{sha256(data)}{ext}"


def edgeone_config(manifest, extra_redirects=()):
    return {
        # Trailing-slash redirects live in middleware.js because edgeone.json redirects drop the request query.
        "redirects": list(extra_redirects),
        # Same policy the www L7 rules enforce today: never serve stale HTML (WeChat WebView).
        "headers": [
            {"source": "/*", "headers": [{"key": "Cache-Control", "value": "no-cache"}]},
        ],
    }


def middleware_source(manifest):
    """Pages middleware for redirects that must retain the complete request query string."""
    paths = [m.path.rstrip("/") for m in manifest.mounts]
    encoded = json.dumps(paths, ensure_ascii=False)
    public_origin = json.dumps(f"https://{manifest.host}")
    return f"""const trailingSlashPaths = new Set({encoded});

export function middleware({{ request, next, redirect }}) {{
  const url = new URL(request.url);
  if (!trailingSlashPaths.has(url.pathname)) return next();
  const target = new URL(url.pathname + url.search, {public_origin});
  target.pathname += "/";
  return redirect(target.toString(), 308);
}}

export const config = {{ matcher: {encoded} }};
"""


ROOT_INDEX = b"""<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex">
<title>WaytoAGI static pages origin</title><p>Origin for pages mounted under www.waytoagi.com.</p>
"""


def assemble(manifest, out):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    state = {"mounts": {}}
    redirects = []
    for m in manifest.mounts:
        src = m.source
        files = read_inline(src["inline"]) if "inline" in src else fetch_tree(src["repo"], src["ref"], src["dir"])
        files = {rel: data for rel, data in files.items() if not excluded(rel, m.exclude)}
        if "index.html" not in files:
            raise SystemExit(f"{m.path}: source has no index.html")
        target = out / m.key
        hashes, offloaded = {}, {}
        for rel, data in sorted(files.items()):
            if rel != "index.html" and offload(manifest, rel, data):
                key = media_key(manifest, data, rel)
                MEDIA_CACHE.mkdir(parents=True, exist_ok=True)
                cached = MEDIA_CACHE / os.path.basename(key)
                if not cached.exists():
                    cached.write_bytes(data)
                offloaded[rel] = {"key": key, "sha256": sha256(data), "size": len(data),
                                  "content_type": mimetypes.guess_type(rel)[0] or "application/octet-stream"}
                # 302, not 301: browsers cache 301 forever, and the key changes whenever the content does.
                # Absolute www URL: the /_media/* rule only exists on www, and a mount may also be served
                # from another host (e.g. waytoagi.com/kemengopc/ or the origin itself).
                redirects.append({"source": m.path + rel, "destination": f"https://{manifest.host}/{key}",
                                  "statusCode": 302})
                continue
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            hashes[rel] = sha256(data)
        # Mounts without offloaded files keep the original tree hash, so they do not look changed.
        tree_input = hashes if not offloaded else {"files": hashes, "offloaded": {r: o["key"] for r, o in offloaded.items()}}
        state["mounts"][m.path] = {
            "source": src,
            "tree": sha256(json.dumps(tree_input, sort_keys=True).encode()),
            "files": hashes,
        }
        if offloaded:
            state["mounts"][m.path]["offloaded"] = offloaded
        note = f", {len(offloaded)} offloaded to OSS" if offloaded else ""
        print(f"  {m.path}: {len(files)} files from {src.get('inline') or src['repo'] + '@' + src['ref'][:7]}{note}")

    (out / "index.html").write_bytes(ROOT_INDEX)
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    config = (json.dumps(edgeone_config(manifest, redirects), indent=2) + "\n").encode()
    middleware = middleware_source(manifest).encode()
    (out / "edgeone.json").write_bytes(config)
    (out / "middleware.js").write_bytes(middleware)
    # Configuration changes must trigger deployment even when every mounted source tree is unchanged.
    state["deployment_config"] = sha256(config + b"\0" + middleware)
    (out / STATE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (out / STATE_PATH).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return state
