"""Upload offloaded files to OSS (content-addressed, immutable). Runs in deploy, before the Pages deploy."""
import os

from . import creds
from .assemble import MEDIA_CACHE

CACHE_CONTROL = "public, max-age=31536000, immutable"  # served as-is through the www /_media/* rule


def bucket(manifest):
    import oss2

    kid, secret = creds.media_upload()
    md = manifest.media
    return oss2.Bucket(oss2.Auth(kid, secret), f"https://{md['endpoint']}", md["bucket"])


def offloaded(state, paths=None):
    """{key: entry} for every offloaded file in the given mounts (all mounts by default)."""
    out = {}
    for path, mount in state["mounts"].items():
        if paths is None or path in paths:
            for entry in mount.get("offloaded", {}).values():
                out[entry["key"]] = entry
    return out


def upload_missing(manifest, state):
    """Put objects that are not in the bucket yet; an existing key already holds identical content."""
    import oss2

    items = offloaded(state)
    if not items:
        return []
    bk = bucket(manifest)
    uploaded = []
    for key, e in sorted(items.items()):
        try:
            meta = bk.head_object(key)
            if meta.headers.get("x-oss-meta-sha256") == e["sha256"]:
                continue
        except oss2.exceptions.NotFound:
            pass
        bk.put_object_from_file(key, str(MEDIA_CACHE / os.path.basename(key)), headers={
            "Content-Type": e["content_type"],
            "Cache-Control": CACHE_CONTROL,
            "x-oss-meta-sha256": e["sha256"],
        })
        uploaded.append(key)
    return uploaded
