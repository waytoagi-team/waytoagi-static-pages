"""Desired www L7 rules (one origin rule per namespace) vs what the zone has; plan or apply.

Apply only creates or modifies rules named by this tool. It never deletes: the router CAM user has no
delete permission. Legacy rules are retired by disabling them first (set_status, reversible), and deleted
later by hand once the namespace rule has proven itself (docs/runbooks/cutover.md).
"""
import json

from . import creds
from .edgeone import teo

RULE_TAG = "static-pages origin"


def rule_name(manifest, prefix):
    return f"{manifest.host} {prefix}* {RULE_TAG}"


def desired_rule(manifest, prefix):
    return {
        "RuleName": rule_name(manifest, prefix),
        "Description": [
            f"Managed by waytoagi-static-pages (mounts.yaml). Route {prefix}* on {manifest.host} to the "
            f"static-pages Makers origin {manifest.origin}, preserving the URI; other paths keep the main-site origin."
        ],
        "Status": "enable",
        "Branches": [{
            # The bare prefix too, so a top-level mount (/deck/) gets its /deck -> /deck/ redirect from Pages.
            "Condition": f"${{http.request.host}} in ['{manifest.host}'] and "
                         f"${{http.request.uri.path}} in ['{prefix}*', '{prefix.rstrip('/')}']",
            "Actions": [
                {"Name": "ModifyOrigin", "ModifyOriginParameters": {
                    "OriginType": "IPDomain", "Origin": manifest.origin,
                    "OriginProtocol": "https", "HTTPSOriginPort": 443,
                }},
                {"Name": "HostHeader", "HostHeaderParameters": {"Action": "custom", "ServerName": manifest.origin}},
                {"Name": "ModifyResponseHeader", "ModifyResponseHeaderParameters": {"HeaderActions": [
                    {"Action": "set", "Name": "Cache-Control", "Value": "no-store, no-cache, must-revalidate, max-age=0"},
                    {"Action": "set", "Name": "Pragma", "Value": "no-cache"},
                    {"Action": "set", "Name": "Expires", "Value": "0"},
                ]}},
            ],
        }],
    }


def _comparable(rule):
    return {k: rule.get(k) for k in ("RuleName", "Description", "Status", "Branches")}


def current_rules(manifest, cli):
    return cli.call_json("DescribeL7AccRules", {"ZoneId": manifest.zone_id, "Limit": 1000})["Response"]["Rules"]


def plan(manifest, cli=None):
    cli = cli or teo(creds.router())
    rules = current_rules(manifest, cli)
    by_name = {r["RuleName"]: r for r in rules}
    actions, notes = [], []
    for ns in manifest.namespaces:
        want = desired_rule(manifest, ns["prefix"])
        have = by_name.get(want["RuleName"])
        if not have:
            actions.append(("create", want, None))
        elif _comparable(have) != _comparable(want):
            actions.append(("modify", want, have))
        # Legacy rules that route paths inside this namespace elsewhere (e.g. per-mount rules to kemengopc).
        for r in rules:
            if r["RuleName"] == want["RuleName"] or r.get("Status") != "enable":
                continue
            cond = json.dumps(r.get("Branches"), ensure_ascii=False)
            if f"'{manifest.host}'" in cond and ns["prefix"] in cond:
                notes.append(f"legacy rule {r['RuleId']} ({r['RuleName']}, priority {r['RulePriority']}) "
                             f"also matches {ns['prefix']}; retire it after verifying the namespace rule")
    return actions, notes


def apply(manifest, actions):
    cli = teo(creds.router())
    done = []
    for kind, want, have in actions:
        if kind == "create":
            resp = cli.call_json("CreateL7AccRules", {"ZoneId": manifest.zone_id, "Rules": [want]})["Response"]
            done.append(f"created {want['RuleName']}: {resp.get('RuleIds')}")
        else:
            rule = {**want, "RuleId": have["RuleId"]}
            cli.call_json("ModifyL7AccRule", {"ZoneId": manifest.zone_id, "Rule": rule})
            done.append(f"modified {have['RuleId']} {want['RuleName']}")
    return done


def set_status(manifest, rule_id, status):
    """Enable / disable one existing rule, keeping everything else as is (reversible retirement)."""
    cli = teo(creds.router())
    rule = next((r for r in current_rules(manifest, cli) if r["RuleId"] == rule_id), None)
    if not rule:
        raise SystemExit(f"rule {rule_id} not found")
    body = {k: rule[k] for k in ("RuleId", "RuleName", "Description", "Branches") if k in rule}
    cli.call_json("ModifyL7AccRule", {"ZoneId": manifest.zone_id, "Rule": {**body, "Status": status}})
    return f"{rule_id} ({rule['RuleName']}): {rule['Status']} -> {status}"
