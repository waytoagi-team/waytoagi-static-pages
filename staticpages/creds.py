"""Credentials: environment variables in CI, .keys/ files locally. Never logged."""
import csv
import os

from .manifest import ROOT

KEYS = ROOT / ".keys"


def pages_token():
    token = os.environ.get("EDGEONE_PAGES_API_TOKEN")
    if not token and (KEYS / "eo_makers_token.txt").exists():
        token = (KEYS / "eo_makers_token.txt").read_text().strip()
    if not token:
        raise SystemExit("missing EDGEONE_PAGES_API_TOKEN")
    return token


def _tencent(env_prefix, key_file):
    sid, skey = os.environ.get(f"{env_prefix}_SECRET_ID"), os.environ.get(f"{env_prefix}_SECRET_KEY")
    if not (sid and skey) and (KEYS / key_file).exists():
        with open(KEYS / key_file, encoding="utf-8-sig") as f:
            row = next(csv.DictReader(f))
        sid, skey = row["SecretId"], row["SecretKey"]
    if not (sid and skey):
        raise SystemExit(f"missing {env_prefix}_SECRET_ID / {env_prefix}_SECRET_KEY")
    from tencentcloud.common import credential

    return credential.Credential(sid, skey)


def deployer():
    """CAM user static-pages-deployer: purge cache."""
    return _tencent("TENCENTCLOUD_DEPLOYER", "static-pages-deployer.csv")


def router():
    """CAM user static-pages-router: read / create / modify L7 rules."""
    return _tencent("TENCENTCLOUD_ROUTER", "static-pages-router.csv")
