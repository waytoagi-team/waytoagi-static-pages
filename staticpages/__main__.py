"""waytoagi-static-pages pipeline.

  python -m staticpages validate            check mounts.yaml
  python -m staticpages build [--smoke]     assemble dist/ + static checks (+ browser smoke)
  python -m staticpages plan                build, then show which mounts differ from the live origin
  python -m staticpages deploy [--force]    build, deploy, verify origin, purge + verify www, regress, notify
  python -m staticpages verify              re-verify origin / www / regression without deploying
  python -m staticpages updates [--open-prs] sources with commits newer than the pinned ref (bump PRs)
  python -m staticpages routes plan|apply   www L7 rules for namespaces
  python -m staticpages routes status RULE_ID enable|disable   retire / restore a rule reversibly
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import assemble, checks, manifest as manifest_mod, verify
from .manifest import ROOT

DIST = ROOT / "dist"
RECORD = ROOT / ".state" / "deploy-record.json"


def fail(title, errors):
    print(f"\n✗ {title}:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)


def origin_url(m, args):
    return (args.origin_url or os.environ.get("ORIGIN_URL") or f"https://{m.origin}").rstrip("/")


def summary(lines):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as f:
            f.write("\n".join(lines) + "\n")


def build(m, smoke=False):
    print("assemble:")
    state = assemble.assemble(m, DIST)
    errors = checks.run(m, DIST)
    if errors:
        fail("static checks failed", errors)
    print("static checks: ok")
    if smoke:
        from . import smoke as smoke_mod

        errors = smoke_mod.run(DIST, m.mounts, state)
        if errors:
            fail("smoke test failed", errors)
        print("smoke: ok")
    return state


def cmd_plan(m, args):
    state = build(m, smoke=args.smoke)
    d = verify.diff(state, verify.live_state(origin_url(m, args)))
    lines = ["### static-pages plan", "", f"origin: {origin_url(m, args)}", ""]
    for p in m.mounts:
        mark = "changed" if p.path in d["changed"] else "unchanged"
        live = "www live" if m.is_live(p) else "www pending"
        lines.append(f"- `{p.path}` {mark} ({live})")
    lines += [f"- `{p}` removed" for p in d["removed"]]
    print("\n".join(lines))
    summary(lines)
    return d


def cmd_deploy(m, args):
    from . import edgeone, notify

    state = build(m, smoke=args.smoke)
    base = origin_url(m, args)
    d = verify.diff(state, verify.live_state(base))
    if not (d["changed"] or d["removed"] or args.force):
        print("nothing changed; not deploying")
        return
    print(f"changed: {d['changed']}  removed: {d['removed']}")

    if m.media:
        from . import media

        uploaded = media.upload_missing(m, state)
        print(f"media: uploaded {len(uploaded)} new object(s) to {m.media['bucket']}" + (f": {uploaded}" if uploaded else ""))

    dep = edgeone.deploy(m, DIST)
    print(f"deployed: {dep['deploymentId']} (production, in use)")

    changed = d["changed"] if not args.force else [mt.path for mt in m.mounts]
    errors = verify.verify_files(base, state, changed, bust=dep["deploymentId"])
    errors += verify.verify_offloaded(base, m.host, state, changed)
    if errors:
        fail("origin does not match dist/", errors)
    print(f"origin verified: {base}")

    by_path = {mt.path: mt for mt in m.mounts}
    live = [p for p in changed if m.is_live(by_path[p])]
    purge_urls = [f"https://{m.host}{p}" for p in live + d["removed"]]
    job = edgeone.purge_prefixes(m, purge_urls) if purge_urls else None
    if job:
        print(f"purged {purge_urls}: job {job}")

    errors = verify.verify_prod(m.host, state, live) + verify.regression(m.host)
    errors += verify.verify_offloaded(f"https://{m.host}", m.host, state, live)
    if errors:
        fail("www verification failed", errors)
    print(f"www verified: {live or '(no active mounts changed)'}; regression ok")

    record = {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "commit": os.environ.get("GITHUB_SHA"),
        "deployment": dep,
        "purge_job": job,
        "changed": {p: {"source": state["mounts"][p]["source"],
                        "index_sha256": state["mounts"][p]["files"]["index.html"],
                        "www": m.is_live(by_path[p])} for p in changed},
        "removed": d["removed"],
    }
    RECORD.parent.mkdir(exist_ok=True)
    RECORD.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    lines = [f"[static-pages] deployed {dep['deploymentId']}" + (f", purge {job}" if job else "")]
    for p, c in record["changed"].items():
        src = c["source"].get("inline") or f"{c['source']['repo']}@{c['source']['ref'][:7]}"
        url = f"https://{m.host}{p}" if c["www"] else f"{base}{p} (www pending)"
        lines.append(f"- {url} ← {src}")
    lines += [f"- removed {p}" for p in d["removed"]]
    print("\n".join(lines))
    summary(["### static-pages deploy", "", *lines])
    notify.send(lines)


def cmd_verify(m, args):
    """Re-verify every mount against the origin (and www for active namespaces) without deploying."""
    state = build(m)
    base = origin_url(m, args)
    errors = verify.verify_files(base, state, [mt.path for mt in m.mounts], bust="verify")
    errors += verify.verify_offloaded(base, m.host, state, [mt.path for mt in m.mounts])
    live = [mt.path for mt in m.mounts if m.is_live(mt)]
    errors += verify.verify_prod(m.host, state, live) + verify.regression(m.host)
    if errors:
        fail("verification failed", errors)
    print(f"verified: origin {base}; www {live or '(no active mounts)'}; regression ok")


def cmd_updates(m, args):
    from . import updates

    items = updates.check(m)
    lines = ["### source updates", ""]
    for it in items:
        mark = "up to date" if it["status"] == "identical" else f"{it['status']} by {it['ahead_by']}"
        lines.append(f"- `{it['path']}` {it['repo']}@{it['ref'][:7]} → {it['latest'][:7]} ({mark}) {it['subject']}")
    print("\n".join(lines))
    summary(lines)
    odd = [it for it in items if it["status"] not in ("identical", "ahead")]
    for it in odd:
        print(f"warning: {it['path']} pinned ref is {it['status']} relative to {it['branch']}; not bumping")
    if args.open_prs:
        for line in updates.open_prs(items):
            print(line)


def cmd_routes(m, args):
    from . import routes

    if args.action == "status":
        print(routes.set_status(m, args.rule_id, args.status))
        return
    actions, notes = routes.plan(m)
    if args.only:
        actions = [a for a in actions if args.only in a[1]["RuleName"]]
    for kind, want, have in actions:
        print(f"{kind}: {want['RuleName']}" + (f" ({have['RuleId']})" if have else ""))
        print(json.dumps(routes._strip_secrets(want), ensure_ascii=False, indent=2))
    for n in notes:
        print(f"note: {n}")
    if not actions:
        print("routes up to date")
    if args.action == "apply" and actions:
        for line in routes.apply(m, actions):
            print(line)


def main():
    ap = argparse.ArgumentParser(prog="staticpages")
    ap.add_argument("--origin-url", help="override https://<origin> (e.g. the .edgeone.cool preset domain)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("validate")
    for name in ("build", "plan", "deploy", "verify"):
        p = sub.add_parser(name)
        if name != "verify":
            p.add_argument("--smoke", action="store_true", help="run the browser smoke test")
        if name == "deploy":
            p.add_argument("--force", action="store_true", help="deploy and verify every mount even if unchanged")
    u = sub.add_parser("updates", help="check sources for commits newer than the pinned refs")
    u.add_argument("--open-prs", action="store_true", help="open / refresh one bump PR per outdated mount")
    r = sub.add_parser("routes")
    r.add_argument("action", choices=["plan", "apply", "status"])
    r.add_argument("rule_id", nargs="?", help="status: rule to change, e.g. rule-3vfh6xhhtr4n")
    r.add_argument("status", nargs="?", choices=["enable", "disable"])
    r.add_argument("--only", help="plan/apply only rules whose name contains this text, e.g. '/_media/'")
    args = ap.parse_args()

    m = manifest_mod.load()
    if args.cmd == "validate":
        print(f"mounts.yaml ok: {len(m.namespaces)} namespaces, {len(m.mounts)} mounts")
    elif args.cmd == "build":
        build(m, smoke=args.smoke)
    elif args.cmd == "plan":
        cmd_plan(m, args)
    elif args.cmd == "deploy":
        cmd_deploy(m, args)
    elif args.cmd == "verify":
        cmd_verify(m, args)
    elif args.cmd == "updates":
        cmd_updates(m, args)
    elif args.cmd == "routes":
        if args.action == "status" and not (args.rule_id and args.status):
            ap.error("routes status needs RULE_ID enable|disable")
        cmd_routes(m, args)


if __name__ == "__main__":
    main()
