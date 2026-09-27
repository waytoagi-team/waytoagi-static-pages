"""Load and validate mounts.yaml."""
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "mounts.yaml"

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
PATH_RE = re.compile(r"^/(?:[a-z0-9][a-z0-9._-]*/)+$")
MEDIA_PREFIX_RE = re.compile(r"^/_?[a-z0-9][a-z0-9._-]*/$")  # e.g. /_media/
# Paths the main site owns; never route these away from it.
RESERVED = ("/", "/zh/", "/en/", "/events/", "/api/", "/_next/", "/static/")


@dataclass
class Mount:
    path: str
    owner: str
    source: dict
    exclude: list = field(default_factory=list)
    smoke: list = field(default_factory=list)

    @property
    def key(self):
        return self.path.strip("/")


@dataclass
class Manifest:
    host: str
    zone_id: str
    origin: str
    pages_project: str
    namespaces: list
    mounts: list
    media: dict = field(default_factory=dict)

    def namespace_of(self, mount):
        return next(n for n in self.namespaces if mount.path.startswith(n["prefix"]))

    def is_live(self, mount):
        return self.namespace_of(mount)["status"] == "active"


def load(path=MANIFEST):
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    mounts = [Mount(**m) for m in raw.get("mounts") or []]
    m = Manifest(
        host=raw["host"],
        zone_id=raw["zone_id"],
        origin=raw["origin"],
        pages_project=raw["pages_project"],
        namespaces=raw.get("namespaces") or [],
        mounts=mounts,
        media=raw.get("media") or {},
    )
    errors = validate(m)
    if errors:
        raise SystemExit("mounts.yaml invalid:\n  " + "\n  ".join(errors))
    return m


def validate(m):
    errors = []
    prefixes = []
    for n in m.namespaces:
        p = n.get("prefix", "")
        if not PATH_RE.match(p):
            errors.append(f"namespace {p!r}: must look like /name/")
        if n.get("status") not in ("pending", "active"):
            errors.append(f"namespace {p!r}: status must be pending or active")
        if p in RESERVED:
            errors.append(f"namespace {p!r}: reserved by the main site")
        prefixes.append(p)
    for a in prefixes:
        for b in prefixes:
            if a != b and b.startswith(a):
                errors.append(f"namespaces {a!r} and {b!r} overlap")

    if m.media:
        missing = {"prefix", "bucket", "endpoint", "region", "min_bytes"} - m.media.keys()
        if missing:
            errors.append(f"media: missing {sorted(missing)}")
        elif not MEDIA_PREFIX_RE.match(m.media["prefix"]) or any(m.media["prefix"].startswith(p) or p.startswith(m.media["prefix"]) for p in prefixes):
            errors.append(f"media.prefix {m.media['prefix']!r}: must look like /name/ and not overlap a namespace")
        if m.media.get("prefix") in RESERVED:
            errors.append(f"media.prefix {m.media['prefix']!r}: reserved by the main site")

    seen = []
    for mt in m.mounts:
        where = f"mount {mt.path!r}"
        if not PATH_RE.match(mt.path):
            errors.append(f"{where}: path must look like /a/b/ (lowercase, trailing slash)")
            continue
        if not any(mt.path.startswith(p) for p in prefixes):
            errors.append(f"{where}: not under a declared namespace")
        for other in seen:
            if mt.path.startswith(other) or other.startswith(mt.path):
                errors.append(f"{where}: overlaps {other!r}")
        seen.append(mt.path)

        src = mt.source or {}
        if "inline" in src:
            if not (ROOT / src["inline"]).is_dir():
                errors.append(f"{where}: inline dir {src['inline']!r} not found")
        elif {"repo", "ref", "dir"} <= src.keys():
            if not SHA_RE.match(str(src["ref"])):
                errors.append(f"{where}: source.ref must be a full 40-char commit SHA")
        else:
            errors.append(f"{where}: source needs either inline, or repo + ref + dir")
        if not mt.owner:
            errors.append(f"{where}: owner required")
    return errors
