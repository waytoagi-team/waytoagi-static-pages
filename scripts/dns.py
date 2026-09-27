#!/usr/bin/env python3
"""Ensure a CNAME (or TXT) record in Aliyun DNS for waytoagi.com. Idempotent; dry-run unless --apply.

Needs: pip install alibabacloud_alidns20150109
Usage: python scripts/dns.py static-origin static-origin.waytoagi.com.pages.dnsoeN.com [--apply]
       python scripts/dns.py <rr> <value> --delete [--apply]   # delete only the record matching rr+type+value
Key: Aliyun AccessKey CSV (columns "AccessKey ID","AccessKey Secret") via --key or ALIYUN_DNS_KEY_FILE
"""
import argparse
import csv
import os
from pathlib import Path

from alibabacloud_alidns20150109 import models as m
from alibabacloud_alidns20150109.client import Client
from alibabacloud_tea_openapi.models import Config

ROOT = Path(__file__).resolve().parent.parent
DOMAIN = "waytoagi.com"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rr", help="host record, e.g. static-origin")
    ap.add_argument("target", help="CNAME target given by EdgeOne Pages when binding the domain, or TXT value")
    ap.add_argument("--type", choices=["CNAME", "TXT"], default="CNAME")
    ap.add_argument("--ttl", type=int, default=600)
    ap.add_argument("--delete", action="store_true", help="delete the record matching rr, type and value")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--key", default=os.environ.get("ALIYUN_DNS_KEY_FILE"), help="Aliyun AccessKey CSV")
    args = ap.parse_args()
    if not args.key:
        ap.error("pass --key or set ALIYUN_DNS_KEY_FILE (the Aliyun account that hosts waytoagi.com DNS)")

    with open(args.key, encoding="utf-8-sig") as f:
        row = next(csv.DictReader(f))
    client = Client(Config(access_key_id=row["AccessKey ID"], access_key_secret=row["AccessKey Secret"],
                           endpoint="alidns.cn-hangzhou.aliyuncs.com"))

    records = client.describe_domain_records(m.DescribeDomainRecordsRequest(
        domain_name=DOMAIN, rrkey_word=args.rr, page_size=100)).body.domain_records.record
    exact = [r for r in records if r.rr == args.rr]
    for r in exact:
        print(f"existing: {r.rr}.{DOMAIN} {r.type} {r.value} ({r.status}, ttl {r.ttl}, id {r.record_id})")

    same = [r for r in exact if r.type == args.type]
    mode = "apply" if args.apply else "dry-run"
    if args.delete:
        match = [r for r in same if r.value.rstrip(".") == args.target.rstrip(".")]
        if not match:
            print("nothing to delete")
        for r in match:
            print(f"[{mode}] delete {r.type} {r.rr}.{DOMAIN} -> {r.value} (id {r.record_id})")
            if args.apply:
                client.delete_domain_record(m.DeleteDomainRecordRequest(record_id=r.record_id))
        return
    # A CNAME cannot coexist with any other record on the same host.
    if [r for r in exact if r.type != args.type and "CNAME" in (r.type, args.type)]:
        raise SystemExit("refusing: conflicting records exist for this host; resolve manually")
    if same and same[0].value.rstrip(".") == args.target.rstrip("."):
        print("up to date")
        return
    if same:
        print(f"[{mode}] update {args.type} {args.rr}.{DOMAIN} -> {args.target}")
        if args.apply:
            client.update_domain_record(m.UpdateDomainRecordRequest(
                record_id=same[0].record_id, rr=args.rr, type=args.type, value=args.target, ttl=args.ttl))
    else:
        print(f"[{mode}] add {args.type} {args.rr}.{DOMAIN} -> {args.target}")
        if args.apply:
            resp = client.add_domain_record(m.AddDomainRecordRequest(
                domain_name=DOMAIN, rr=args.rr, type=args.type, value=args.target, ttl=args.ttl))
            print(f"created record {resp.body.record_id}")


if __name__ == "__main__":
    main()
