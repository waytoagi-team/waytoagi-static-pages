"""Check every publish candidate; the Pages size limit applies only to dist/."""
import json
import re
import subprocess

from .assemble import MEDIA_CACHE, STATE_PATH

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


def _check_file(f, rel, mount_path, pages=True):
    errors = []
    data = f.read_bytes()
    if pages and len(data) > MAX_FILE_BYTES:
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
            errors += _check_file(f, rel, m.path)
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
