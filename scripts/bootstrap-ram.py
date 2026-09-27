#!/usr/bin/env python3
"""Create the Aliyun RAM policies / users for offloaded media (OSS bucket, `_media/` prefix only).

  static-pages-media-origin  oss:GetObject                 used by the EdgeOne L7 origin (AWSS3, private v4)
  static-pages-media-upload  oss:PutObject, oss:GetObject  used by the pipeline to upload offloaded files

Idempotent; dry-run unless --apply. New AccessKeys go to .keys/<user>.csv (mode 600), never printed.
Needs: pip install alibabacloud_ram20150501
Usage: python scripts/bootstrap-ram.py --key <admin AccessKey CSV> [--apply]
"""
import argparse
import csv
import json
import os
from pathlib import Path

from alibabacloud_ram20150501 import models as m
from alibabacloud_ram20150501.client import Client
from alibabacloud_tea_openapi.models import Config

ROOT = Path(__file__).resolve().parent.parent
BUCKET = "waytoagi-static-pages-media"
PREFIX = "_media/"

USERS = {
    "static-pages-media-origin": (["oss:GetObject"], "waytoagi-static-pages: EdgeOne origin for www /_media/*"),
    "static-pages-media-upload": (["oss:PutObject", "oss:GetObject"], "waytoagi-static-pages: pipeline uploads to /_media/"),
}


def policy(actions):
    return json.dumps({"Version": "1", "Statement": [
        {"Effect": "Allow", "Action": actions, "Resource": [f"acs:oss:*:*:{BUCKET}/{PREFIX}*"]},
    ]})


def exists(fn):
    try:
        fn()
        return True
    except Exception as e:
        if "EntityNotExist" in str(e):
            return False
        raise


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", required=True, help="admin Aliyun AccessKey CSV")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    with open(args.key, encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    ram = Client(Config(access_key_id=row["AccessKey ID"], access_key_secret=row["AccessKey Secret"],
                        endpoint="ram.aliyuncs.com"))
    mode = "APPLY" if args.apply else "DRY-RUN"
    for name, (actions, desc) in USERS.items():
        print(f"[{mode}] {name}: {actions} on {BUCKET}/{PREFIX}*")
        if exists(lambda: ram.get_policy(m.GetPolicyRequest(policy_name=name, policy_type="Custom"))):
            print("  policy exists")
        elif args.apply:
            ram.create_policy(m.CreatePolicyRequest(policy_name=name, policy_document=policy(actions), description=desc))
            print("  policy created")
        if exists(lambda: ram.get_user(m.GetUserRequest(user_name=name))):
            print("  user exists (keys not rotated)")
        elif args.apply:
            ram.create_user(m.CreateUserRequest(user_name=name, comments=desc))
            key = ram.create_access_key(m.CreateAccessKeyRequest(user_name=name)).body.access_key
            out = ROOT / ".keys" / f"{name}.csv"
            fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", newline="") as f:
                csv.writer(f).writerows([["AccessKey ID", "AccessKey Secret"], [key.access_key_id, key.access_key_secret]])
            print(f"  user created; key saved to {out.relative_to(ROOT)}")
        if args.apply:
            attached = ram.list_policies_for_user(m.ListPoliciesForUserRequest(user_name=name)).body.policies.policy
            if any(p.policy_name == name for p in attached):
                print("  policy already attached")
            else:
                ram.attach_policy_to_user(m.AttachPolicyToUserRequest(policy_name=name, policy_type="Custom", user_name=name))
                print("  policy attached")


if __name__ == "__main__":
    main()
