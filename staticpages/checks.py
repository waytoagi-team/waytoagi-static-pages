"""Check every publish candidate; the Pages size limit applies only to dist/."""
import fnmatch
import hashlib
import html.parser
import json
import posixpath
import re
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .assemble import MEDIA_CACHE, STATE_PATH, STAY_ON_PAGES

MAX_FILE_BYTES = 25 * 1024 * 1024

SECRET_PATTERNS = {
    "Tencent Cloud SecretId": re.compile(rb"AKID[0-9A-Za-z]{32}"),
    "Aliyun AccessKey": re.compile(rb"LTAI[0-9A-Za-z]{12,20}"),
    "GitHub token": re.compile(rb"gh[pousr]_[0-9A-Za-z]{36}|github_pat_[0-9A-Za-z_]{40,}"),
    "Anthropic key": re.compile(rb"sk-ant-[0-9A-Za-z_-]{20,}"),
    "OpenAI-style key": re.compile(rb"\bsk-[0-9A-Za-z]{32,}\b"),
    "Slack token": re.compile(rb"xox[abprs]-[0-9A-Za-z-]{10,}"),
    "Private key": re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS access key": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
}
# src="/x", href="/x", url(/x): resolve against the www root, not the mount, and break once mounted.
ABS_REF = re.compile(rb"""(?:\b(?:src|href|action)\s*=\s*["']|url\(\s*["']?)(/(?!/)[^"')\s]*)""")


SPLIT_HINT = {
    ".css": "move inline base64 fonts/images into separate files and reference them with relative url()",
    "html": "move embedded data (inline JSON, base64 images/fonts/media, large inline scripts) into separate "
            ".json/.js/asset files next to the page and load them by relative path, or split the page into "
            "several pages",
}


def page_limit(manifest):
    """HTML/CSS must stay on Pages; anything at the offload threshold would have been offloaded."""
    return min(MAX_FILE_BYTES, manifest.media["min_bytes"]) if manifest.media else MAX_FILE_BYTES


def _check_file(f, rel, mount_path, pages=True, html_limit=MAX_FILE_BYTES):
    errors = []
    data = f.read_bytes()
    stays = f.suffix.lower() in STAY_ON_PAGES
    if pages and stays and len(data) >= html_limit:
        hint = SPLIT_HINT[".css" if f.suffix.lower() == ".css" else "html"]
        errors.append(f"{rel}: {len(data)} bytes; {f.suffix.lower()} files cannot be offloaded to OSS (their relative "
                      f"URLs would break) and must be under {html_limit} bytes. Split it: {hint}. Large asset files "
                      f"are then offloaded automatically.")
    elif pages and len(data) > MAX_FILE_BYTES:
        errors.append(f"{rel}: {len(data)} bytes exceeds {MAX_FILE_BYTES}")
    for name, pat in SECRET_PATTERNS.items():
        if pat.search(data):
            errors.append(f"{rel}: looks like it contains a {name}")
    if f.suffix in (".html", ".htm", ".css"):
        for ref in sorted(set(ABS_REF.findall(data))):
            ref = ref.decode(errors="replace")
            if not ref.startswith(mount_path):
                errors.append(f"{rel}: root-absolute reference {ref!r} breaks under {mount_path}; use a relative path")
    return errors


def offloaded_files(state):
    """Only objects referenced by this build, not stale entries in the local cache."""
    for mount_path, mount in state["mounts"].items():
        for rel, entry in mount.get("offloaded", {}).items():
            yield mount_path, rel, MEDIA_CACHE / entry["key"].rsplit("/", 1)[-1]


def run(manifest, out, state, mounts=None):
    errors = []
    selected = mounts if mounts is not None else manifest.mounts
    for m in selected:
        base = out / m.key
        for f in sorted(p for p in base.rglob("*") if p.is_file()):
            rel = f"{m.path}{f.relative_to(base)}"
            errors += _check_file(f, rel, m.path, html_limit=page_limit(manifest))
    for m in selected:
        errors += missing_refs(m, out, state)
    paths = {m.path for m in selected}
    for mount_path, rel, f in offloaded_files(state):
        if mount_path in paths:
            errors += _check_file(f, mount_path + rel, mount_path, pages=False)
    return errors


def checksum_scan_config(out, state):
    """Allow only verified file-checksum lines in the generated manifest.

    Names such as github_api.py look like credential identifiers to Gitleaks when
    paired with a SHA-256. Keep scanning all published bytes and other metadata.
    """
    root = out.resolve()
    lines = set()
    for mount_path, mount in state["mounts"].items():
        for rel, digest in mount["files"].items():
            target = (root / mount_path.strip("/") / rel).resolve()
            if not target.is_relative_to(root):
                raise ValueError("Manifest checksum path leaves the publish directory")
            if (not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest)
                    or hashlib.sha256(target.read_bytes()).hexdigest() != digest):
                raise ValueError(f"Manifest checksum does not match published file: {rel}")
            lines.add(r"^\s*" + re.escape(json.dumps(rel)) + r":\s*"
                      + re.escape(json.dumps(digest)) + r",?\s*$")
    config = '[extend]\nuseDefault = true\n'
    if lines:
        config += ('[[rules]]\nid = "generic-api-key"\n[[rules.allowlists]]\n'
                   'description = "Verified generated file checksum lines only"\n'
                   'condition = "AND"\nregexTarget = "line"\n'
                   'paths = ' + json.dumps(["^" + re.escape(str(root / STATE_PATH)) + "$"]) + '\n'
                   'regexes = ' + json.dumps(sorted(lines)) + '\n')
    return config


def scan_secrets(out, executable="gitleaks"):
    """Run Gitleaks on dist/ and each current OSS candidate, with no file-size cutoff."""
    state = json.loads((out / STATE_PATH).read_text())
    targets = [out, *sorted({f for _, _, f in offloaded_files(state)})]
    with tempfile.TemporaryDirectory(prefix="staticpages-gitleaks-") as directory:
        config = Path(directory) / "gitleaks.toml"
        config.write_text(checksum_scan_config(out, state))
        for target in targets:
            subprocess.run([executable, "dir", str(target), "--no-banner", "--redact",
                            "--max-target-megabytes", "0", "--config", str(config)], check=True)


# ---- relative references ---------------------------------------------------------------------------

URL_ATTRS = {"src", "href", "poster"}
CSS_URL = re.compile(r"""url\(\s*(['"]?)([^'")]+)\1\s*\)|@import\s+(['"])([^'"]+)\3""")
SCHEME = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
TEMPLATE = ("${", "{{", "<%", "' +", "\" +")


class _RefParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.refs, self._in_style = [], False

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if not value:
                continue
            if name in URL_ATTRS:
                self.refs.append(value)
            elif name == "srcset":
                self.refs += [part.strip().split()[0] for part in value.split(",") if part.strip()]
            elif name == "style":
                self.refs += _css_refs(value)
        self._in_style = tag == "style"

    def handle_endtag(self, tag):
        self._in_style = False

    def handle_data(self, data):
        if self._in_style:
            self.refs += _css_refs(data)


def _css_refs(text):
    return [m.group(2) or m.group(4) for m in CSS_URL.finditer(text)]


def _target(ref, file_rel, mount_path):
    """Mount-relative path a reference points at, None if it is not ours to check, or '..' if it escapes."""
    ref = ref.strip()
    if (not ref or ref.startswith(("#", "?", "//")) or SCHEME.match(ref) or any(t in ref for t in TEMPLATE)):
        return None
    path = unquote(urlsplit(ref).path)
    if not path:
        return None
    if path.startswith("/"):
        if not path.startswith(mount_path):
            return None  # reported by ABS_REF
        return path[len(mount_path):]
    joined = posixpath.normpath(posixpath.join(posixpath.dirname(file_rel), path))
    if joined == ".." or joined.startswith("../"):
        return ".."
    target = "" if joined == "." else joined
    return target + "/" if path.endswith("/") and target else target


def _published(target, files):
    if target in files:
        return True
    base = target.rstrip("/")
    return (f"{base}/index.html" if base else "index.html") in files


def missing_refs(mount, out, state):
    """HTML/CSS references to files this mount does not publish (e.g. copies whose assets did not come along)."""
    base = out / mount.key
    files = {str(p.relative_to(base)) for p in base.rglob("*") if p.is_file()}
    files |= set(state["mounts"].get(mount.path, {}).get("offloaded", {}))
    errors = []
    per_file_limit = 5
    for f in sorted(p for p in base.rglob("*") if p.suffix.lower() in (".html", ".htm", ".css")):
        file_errors = []
        file_rel = str(f.relative_to(base))
        text = f.read_text(encoding="utf-8", errors="replace")
        if f.suffix.lower() == ".css":
            refs = _css_refs(text)
        else:
            parser = _RefParser()
            parser.feed(text)
            refs = parser.refs
        for ref in sorted(set(refs)):
            target = _target(ref, file_rel, mount.path)
            if target is None or any(fnmatch.fnmatch(target, g) for g in mount.allow_missing):
                continue
            if target == "..":
                file_errors.append(f"{mount.path}{file_rel}: reference {ref!r} leaves {mount.path}; "
                                   "link across mounts with an absolute https:// URL instead")
            elif not _published(target, files):
                file_errors.append(f"{mount.path}{file_rel}: reference {ref!r} points to {mount.path}{target}, "
                                   "which is not published (missing, excluded, or a copied page without its assets)")
        errors += file_errors[:per_file_limit]
        if len(file_errors) > per_file_limit:
            errors.append(f"{mount.path}{file_rel}: ... and {len(file_errors) - per_file_limit} more missing references")
    return errors
