#!/usr/bin/env python3
"""Show or bind an EdgeOne Pages custom domain via the teo Pages resource gateway.

The Makers SDK / Pages API have no domain actions. The console uses the teo API
`DescribePagesResources` / `CreatePagesResources` with an `Interface` such as
`pages:DescribePagesZoneCustomDomains` / `pages:CreatePagesZoneCustomDomain`; a CAM key works too.

Usage:
  python scripts/pages-domain.py                     # list domains of the project (CNAME target, status)
  python scripts/pages-domain.py --bind DOMAIN       # bind DOMAIN to the Production env (idempotent)
  python scripts/pages-domain.py --wait DOMAIN       # poll until DOMAIN is online
  python scripts/pages-domain.py --cert DOMAIN       # enable the EdgeOne free certificate

Certificate: ModifyHostsCertificate Mode=eofreecert on the Pages zone, the same call as the console's
"free certificate" button. No separate ApplyFreeCertificate / DNS challenge is needed.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

from tencentcloud.common import credential
from tencentcloud.common.common_client import CommonClient
from tencentcloud.common.profile.client_profile import ClientProfile

ROOT = Path(__file__).resolve().parent.parent
PAGES_ZONE = "zone-3tbtpw8l2gu4"  # default-pages-zone
PROJECT_ID = "makers-obe4szcie7gs"  # waytoagi-static-pages


def client(key_file):
    with open(key_file, encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    cred = credential.Credential(row["SecretId"], row["SecretKey"])
    return CommonClient("teo", "2022-09-01", cred, "ap-guangzhou", profile=ClientProfile())


def gateway(cli, action, interface, payload):
    resp = cli.call_json(action, {"ZoneId": PAGES_ZONE, "Interface": interface, "Payload": json.dumps(payload)})
    return json.loads(resp["Response"].get("Result") or "{}")


def domains(cli, project):
    return gateway(cli, "DescribePagesResources", "pages:DescribePagesZoneCustomDomains",
                   {"ProjectId": project})["PagesDomains"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=PROJECT_ID)
    ap.add_argument("--key", default=str(ROOT / ".keys/TencentCloudSecretKey.csv"))
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--bind", metavar="DOMAIN")
    g.add_argument("--wait", metavar="DOMAIN")
    g.add_argument("--cert", metavar="DOMAIN")
    args = ap.parse_args()
    cli = client(args.key)

    if args.bind:
        if any(d["Domain"] == args.bind for d in domains(cli, args.project)):
            print(f"{args.bind} already bound")
        else:
            gateway(cli, "CreatePagesResources", "pages:CreatePagesZoneCustomDomain",
                    {"ProjectId": args.project, "Domain": args.bind, "Env": "Production"})
            print(f"bound {args.bind}")

    if args.wait:
        deadline = time.time() + 900
        while time.time() < deadline:
            d = next((d for d in domains(cli, args.project) if d["Domain"] == args.wait), None)
            status = d and d["Status"]
            print(f"{args.wait}: {status}")
            if status == "online":
                return
            time.sleep(20)
        sys.exit(f"{args.wait} not online after 15 min")

    if args.cert:
        cli.call_json("ModifyHostsCertificate", {"ZoneId": PAGES_ZONE, "Hosts": [args.cert], "Mode": "eofreecert"})
        print(f"eofreecert enabled for {args.cert}")

    for d in domains(cli, args.project):
        print(f"{d['Type']:7} {d['Domain']:45} status={d['Status']:8} cname={d.get('Cname')} current={d.get('CurrentCname')}")


if __name__ == "__main__":
    main()
