"""Build dist/ from mounts.yaml: fetch each source at its pinned SHA, copy into its mount dir."""
import base64
import fnmatch
import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile

from .manifest import ROOT

CACHE = ROOT / ".cache" / "sources"
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


def edgeone_config(manifest):
    return {
        "redirects": [
            {"source": m.path.rstrip("/"), "destination": m.path, "statusCode": 308} for m in manifest.mounts
        ],
        # Same policy the www L7 rules enforce today: never serve stale HTML (WeChat WebView).
        "headers": [
            {"source": "/*", "headers": [{"key": "Cache-Control", "value": "no-cache"}]},
        ],
    }


ROOT_INDEX = b"""<!doctype html><meta charset="utf-8"><meta name="robots" content="noindex">
<title>WaytoAGI static pages origin</title><p>Origin for pages mounted under www.waytoagi.com.</p>
"""


def assemble(manifest, out):
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    state = {"mounts": {}}
    for m in manifest.mounts:
        src = m.source
        files = read_inline(src["inline"]) if "inline" in src else fetch_tree(src["repo"], src["ref"], src["dir"])
        files = {rel: data for rel, data in files.items() if not excluded(rel, m.exclude)}
        if "index.html" not in files:
            raise SystemExit(f"{m.path}: source has no index.html")
        target = out / m.key
        hashes = {}
        for rel, data in sorted(files.items()):
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            hashes[rel] = sha256(data)
        state["mounts"][m.path] = {
            "source": src,
            "tree": sha256(json.dumps(hashes, sort_keys=True).encode()),
            "files": hashes,
        }
        print(f"  {m.path}: {len(files)} files from {src.get('inline') or src['repo'] + '@' + src['ref'][:7]}")

    (out / "index.html").write_bytes(ROOT_INDEX)
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (out / "edgeone.json").write_text(json.dumps(edgeone_config(manifest), indent=2) + "\n")
    (out / STATE_PATH).parent.mkdir(parents=True, exist_ok=True)
    (out / STATE_PATH).write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    return state
