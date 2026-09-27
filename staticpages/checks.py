"""Check every publish candidate; the Pages size limit applies only to dist/."""
import json
import re
import subprocess

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
    paths = {m.path for m in selected}
    for mount_path, rel, f in offloaded_files(state):
        if mount_path in paths:
            errors += _check_file(f, mount_path + rel, mount_path, pages=False)
    return errors


def scan_secrets(out, executable="gitleaks"):
    """Run Gitleaks on dist/ and each current OSS candidate, with no file-size cutoff."""
    state = json.loads((out / STATE_PATH).read_text())
    targets = [out, *sorted({f for _, _, f in offloaded_files(state)})]
    for target in targets:
        subprocess.run([executable, "dir", str(target), "--no-banner", "--redact",
                        "--max-target-megabytes", "0"], check=True)
