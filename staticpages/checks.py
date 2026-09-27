"""Static checks on dist/: leaked credentials, root-absolute references, file size."""
import re

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


def run(manifest, out, mounts=None):
    errors = []
    for m in mounts or manifest.mounts:
        base = out / m.key
        for f in sorted(p for p in base.rglob("*") if p.is_file()):
            rel = f"{m.path}{f.relative_to(base)}"
            data = f.read_bytes()
            if len(data) > MAX_FILE_BYTES:
                errors.append(f"{rel}: {len(data)} bytes exceeds {MAX_FILE_BYTES}")
            for name, pat in SECRET_PATTERNS.items():
                if pat.search(data):
                    errors.append(f"{rel}: looks like it contains a {name}")
            if f.suffix in (".html", ".htm", ".css"):
                for ref in sorted(set(ABS_REF.findall(data))):
                    ref = ref.decode(errors="replace")
                    if not ref.startswith(m.path):
                        errors.append(f"{rel}: root-absolute reference {ref!r} breaks under {m.path}; use a relative path")
    return errors
