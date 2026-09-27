"""Find mounts whose source dir has commits newer than the pinned ref; open / refresh one bump PR per mount.

Run on a schedule (.github/workflows/updates.yml). PRs are never merged automatically: a person reviews
the CI result and merges, and the deploy workflow publishes it.
"""
import json
import os
import re
import subprocess
import urllib.request

from .manifest import MANIFEST

API = "https://api.github.com"


def _token():
    # SOURCE_GITHUB_TOKEN can read the private sources (and public ones); fall back to the workflow token.
    return os.environ.get("SOURCE_GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")


def gh_api(path):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "waytoagi-static-pages"}
    if _token():
        headers["Authorization"] = f"Bearer {_token()}"
    with urllib.request.urlopen(urllib.request.Request(f"{API}{path}", headers=headers), timeout=30) as resp:
        return json.load(resp)


def check(manifest):
    """[{path, repo, dir, ref, latest, status, ahead_by, subject}] for mounts with a repo source."""
    results = []
    for m in manifest.mounts:
        src = m.source
        if "repo" not in src:
            continue
        repo, subdir, ref = src["repo"], src["dir"], src["ref"]
        branch = src.get("branch") or gh_api(f"/repos/{repo}")["default_branch"]
        commits = gh_api(f"/repos/{repo}/commits?sha={branch}&path={subdir}&per_page=1")
        latest = commits[0]["sha"] if commits else ref
        item = {"path": m.path, "key": m.key, "repo": repo, "dir": subdir, "branch": branch,
                "ref": ref, "latest": latest, "status": "identical", "ahead_by": 0, "subject": ""}
        if latest != ref:
            cmp = gh_api(f"/repos/{repo}/compare/{ref}...{latest}")
            item["status"], item["ahead_by"] = cmp["status"], cmp.get("ahead_by", 0)
            item["subject"] = commits[0]["commit"]["message"].split("\n")[0]
        results.append(item)
    return results


def bump_ref(text, mount_path, old, new):
    """Replace the ref of one mount in mounts.yaml text, keeping comments and layout."""
    block = re.search(rf"(?ms)^  - path: {re.escape(mount_path)}\n.*?(?=^  - path: |\Z)", text)
    if not block or old not in block.group(0):
        raise SystemExit(f"cannot find ref {old} under {mount_path} in mounts.yaml")
    new_block = block.group(0).replace(f"ref: {old}", f"ref: {new}", 1)
    return text[:block.start()] + new_block + text[block.end():]


def run(*cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True).stdout.strip()


def open_prs(items, base="main"):
    """One branch + PR per mount (auto-bump/<key>), force-updated to the newest commit."""
    done = []
    for it in items:
        if it["status"] != "ahead":
            continue
        branch = "auto-bump/" + it["key"].replace("/", "-")
        remote = run("git", "ls-remote", "--heads", "origin", branch)
        if remote:
            run("git", "fetch", "-q", "origin", branch)
            if f"ref: {it['latest']}" in run("git", "show", f"origin/{branch}:mounts.yaml"):
                done.append(f"{it['path']}: PR branch already at {it['latest'][:7]}")
                continue
        run("git", "checkout", "-q", "-B", branch, f"origin/{base}")
        MANIFEST.write_text(bump_ref(MANIFEST.read_text(encoding="utf-8"), it["path"], it["ref"], it["latest"]),
                            encoding="utf-8")
        title = f"Bump {it['path']} to {it['repo']}@{it['latest'][:7]}"
        run("git", "commit", "-q", "-am", f"{title}\n\n{it['subject']}")
        run("git", "push", "-q", "-f", "origin", branch)
        body = (
            f"Automated by `updates` workflow.\n\n"
            f"- Mount: `{it['path']}`\n"
            f"- Source: `{it['repo']}` `{it['dir']}` ({it['branch']})\n"
            f"- `{it['ref'][:7]}` → `{it['latest'][:7]}`, {it['ahead_by']} commit(s) ahead: "
            f"https://github.com/{it['repo']}/compare/{it['ref'][:7]}...{it['latest'][:7]}\n"
            f"- Latest: {it['subject']}\n\n"
            f"Review the `ci` check (assemble, static checks, smoke test, diff vs live), then merge to deploy."
        )
        existing = run("gh", "pr", "list", "--head", branch, "--state", "open", "--json", "number", "--jq", ".[0].number")
        if existing:
            run("gh", "pr", "edit", existing, "--title", title, "--body", body)
            done.append(f"{it['path']}: updated PR #{existing} → {it['latest'][:7]}")
        else:
            url = run("gh", "pr", "create", "--base", base, "--head", branch, "--title", title, "--body", body)
            done.append(f"{it['path']}: opened {url}")
        if os.environ.get("DISPATCH_CI") == "1":
            # PRs created with GITHUB_TOKEN do not start workflows; workflow_dispatch does.
            run("gh", "workflow", "run", "ci", "--ref", branch)
        run("git", "checkout", "-q", base)
    return done
