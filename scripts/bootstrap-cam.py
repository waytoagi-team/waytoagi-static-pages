#!/usr/bin/env python3
"""Create the CAM policies and sub-users used by the static-pages pipeline.

Idempotent. Dry-run by default; pass --apply to create. Never prints secrets:
new sub-user keys are written to .keys/<user>.csv (mode 600).

Usage: python scripts/bootstrap-cam.py [--apply] [--admin-key .keys/TencentCloudSecretKey.csv]
"""
import argparse
import csv
import json
import os
import sys
from pathlib import Path

from tencentcloud.cam.v20190116 import cam_client, models as cam_models
from tencentcloud.common import credential
from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
from tencentcloud.sts.v20180813 import sts_client, models as sts_models

ROOT = Path(__file__).resolve().parent.parent
KEYS = ROOT / ".keys"
ZONE_ID = "zone-3tbsf8e3cb9x"


def policies(account_id):
    zone = f"qcs::teo::uin/{account_id}:zone/{ZONE_ID}"
    return {
        "static-pages-deployer": {
            "version": "2.0",
            "statement": [
                {"effect": "allow", "action": ["teo:CreatePurgeTask", "teo:DescribePurgeTasks"], "resource": [zone]},
                {"effect": "allow", "action": ["teo:DescribeZones"], "resource": ["*"]},
            ],
        },
        "static-pages-router": {
            "version": "2.0",
            "statement": [
                {
                    "effect": "allow",
                    "action": ["teo:DescribeL7AccRules", "teo:CreateL7AccRules", "teo:ModifyL7AccRule"],
                    "resource": [zone],
                },
            ],
        },
    }


REMARKS = {
    "static-pages-deployer": "waytoagi-static-pages CI: purge mount-path cache",
    "static-pages-router": "waytoagi-static-pages CI: manage prefix L7 rules (approval required)",
}


def load_cred(path):
    with open(path, encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    return credential.Credential(row["SecretId"], row["SecretKey"])


def call(client, name, req_cls, **params):
    req = req_cls()
    req.from_json_string(json.dumps(params))
    return json.loads(getattr(client, name)(req).to_json_string())


def find_policy(cam, name):
    resp = call(cam, "ListPolicies", cam_models.ListPoliciesRequest, Keyword=name, Scope="Local", Rp=200)
    return next((p["PolicyId"] for p in resp.get("List") or [] if p["PolicyName"] == name), None)


def find_user(cam, name):
    try:
        return call(cam, "GetUser", cam_models.GetUserRequest, Name=name)["Uin"]
    except TencentCloudSDKException as e:
        if "UserNotExist" in (e.code or ""):
            return None
        raise


def attached(cam, uin):
    resp = call(cam, "ListAttachedUserPolicies", cam_models.ListAttachedUserPoliciesRequest, TargetUin=uin, Rp=200)
    return {p["PolicyId"] for p in resp.get("List") or []}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--admin-key", default=str(KEYS / "TencentCloudSecretKey.csv"))
    args = ap.parse_args()

    cred = load_cred(args.admin_key)
    ident = call(sts_client.StsClient(cred, "ap-guangzhou"), "GetCallerIdentity", sts_models.GetCallerIdentityRequest)
    print(f"caller: {ident['Arn']} (account {ident['AccountId']}, type {ident['Type']})")

    cam = cam_client.CamClient(cred, "")
    mode = "APPLY" if args.apply else "DRY-RUN"
    for name, doc in policies(ident["AccountId"]).items():
        print(f"\n[{mode}] {name}")

        policy_id = find_policy(cam, name)
        if policy_id:
            print(f"  policy exists: {policy_id}")
        elif args.apply:
            policy_id = call(cam, "CreatePolicy", cam_models.CreatePolicyRequest,
                             PolicyName=name, PolicyDocument=json.dumps(doc), Description=REMARKS[name])["PolicyId"]
            print(f"  policy created: {policy_id}")
        else:
            print("  policy would be created")

        uin = find_user(cam, name)
        if uin:
            print(f"  user exists: uin {uin} (existing keys are not rotated)")
        elif args.apply:
            resp = call(cam, "AddUser", cam_models.AddUserRequest,
                        Name=name, Remark=REMARKS[name], ConsoleLogin=0, UseApi=1)
            uin = resp["Uin"]
            out = KEYS / f"{name}.csv"
            fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", newline="") as f:
                csv.writer(f).writerows([["SecretId", "SecretKey"], [resp["SecretId"], resp["SecretKey"]]])
            print(f"  user created: uin {uin}; key saved to {out.relative_to(ROOT)}")
        else:
            print("  user would be created (API only, no console login)")

        if uin and policy_id:
            if policy_id in attached(cam, uin):
                print("  policy already attached")
            elif args.apply:
                call(cam, "AttachUserPolicy", cam_models.AttachUserPolicyRequest, PolicyId=policy_id, AttachUin=uin)
                print("  policy attached")
            else:
                print("  policy would be attached")


if __name__ == "__main__":
    try:
        main()
    except TencentCloudSDKException as e:
        print(f"error: {e.code}: {e.message} (RequestId {e.requestId})", file=sys.stderr)
        sys.exit(1)
