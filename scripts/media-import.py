#!/usr/bin/env python3
"""Import files that cannot live in a source repo (e.g. > 100MB, or already on OSS) into the media bucket.

Each file is stored content-addressed as <media.prefix><sha256>.<ext> with the same metadata the pipeline
uses, and the script prints the URL to reference from the page: https://<host>/<key>. Idempotent.

Sources: local paths, or oss://<bucket>/<key> (read with --src-key, an Aliyun AccessKey CSV that can read
that bucket). Uploads use the static-pages-media-upload key (.keys/ or ALIYUN_MEDIA_UPLOAD_KEY_ID/SECRET).

Usage: python scripts/media-import.py [--src-key CSV] <file | oss://bucket/key> ...
"""
import argparse
import csv
import hashlib
import mimetypes
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import oss2  # noqa: E402

from staticpages import manifest as manifest_mod  # noqa: E402
from staticpages.media import CACHE_CONTROL, bucket  # noqa: E402


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch_oss(url, key_csv, workdir):
    bucket_name, key = url[len("oss://"):].split("/", 1)
    with open(key_csv, encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    auth = oss2.Auth(row["AccessKey ID"], row["AccessKey Secret"])
    info = oss2.Service(auth, "https://oss-cn-hangzhou.aliyuncs.com")
    loc = next(b.location for b in oss2.BucketIterator(info) if b.name == bucket_name)
    local = Path(workdir) / os.path.basename(key)
    oss2.Bucket(auth, f"https://{loc}.aliyuncs.com", bucket_name).get_object_to_file(key, str(local))
    return local


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sources", nargs="+")
    ap.add_argument("--src-key", help="Aliyun AccessKey CSV that can read oss:// sources")
    args = ap.parse_args()
    m = manifest_mod.load()
    dst = bucket(m)
    with tempfile.TemporaryDirectory() as work:
        for src in args.sources:
            local = fetch_oss(src, args.src_key, work) if src.startswith("oss://") else Path(src)
            digest = sha256_file(local)
            key = f"{m.media['prefix'].lstrip('/')}{digest}{local.suffix.lower()}"
            try:
                exists = dst.head_object(key).headers.get("x-oss-meta-sha256") == digest
            except oss2.exceptions.NotFound:
                exists = False
            if not exists:
                dst.put_object_from_file(key, str(local), headers={
                    "Content-Type": mimetypes.guess_type(local.name)[0] or "application/octet-stream",
                    "Cache-Control": CACHE_CONTROL,
                    "x-oss-meta-sha256": digest,
                })
            print(f"{src}\t{os.path.getsize(local)}\t{'exists' if exists else 'uploaded'}\thttps://{m.host}/{key}")


if __name__ == "__main__":
    main()
