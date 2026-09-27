"""EdgeOne: Pages deploy / deployment status (Pages API token) and cache purge (CAM deployer)."""
import json
import os
import subprocess
import time
import urllib.request

from . import creds

EDGEONE_CLI = "edgeone@1.6.41"
PAGES_API = "https://pages-api.cloud.tencent.com/v1"  # China site; the project lives there


def pages_api(action, **params):
    req = urllib.request.Request(
        PAGES_API,
        data=json.dumps({"Action": action, **params}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {creds.pages_token()}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.load(resp)
    if body.get("Code") not in (0, None):
        raise SystemExit(f"Pages API {action} failed: {body.get('Code')} {body.get('Message')}")
    return body["Data"]["Response"]


def project_id(name):
    projects = pages_api("DescribePagesProjects", Offset=0, Limit=100)["Projects"]
    match = [p for p in projects if p["Name"] == name]
    if not match:
        raise SystemExit(f"Pages project {name!r} not found")
    return match[0]["ProjectId"]


def deploy(manifest, out):
    """Upload dist/ as a production deployment; return the deployment once it serves production."""
    env = {**os.environ, "EDGEONE_PAGES_API_TOKEN": creds.pages_token()}
    cmd = [
        "npx", "--yes", EDGEONE_CLI, "makers", "deploy", str(out),
        "-n", manifest.pages_project, "-e", "production", "-a", "global",
        "--json", "--skip-ai-gateway-sync", "-t", env["EDGEONE_PAGES_API_TOKEN"],
    ]
    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    lines = [line for line in proc.stdout.splitlines() if line.startswith("{")]
    if proc.returncode or not lines:
        tail = (proc.stdout + proc.stderr)[-2000:].replace(env["EDGEONE_PAGES_API_TOKEN"], "***")
        raise SystemExit(f"edgeone deploy failed:\n{tail}")
    result = json.loads(lines[-1])
    if result.get("status") != "success":
        raise SystemExit(f"edgeone deploy failed: {result}")
    return wait_deployment(result["projectId"], result["deploymentId"])


def wait_deployment(pid, deployment_id, timeout=600):
    """Poll by deployment ID (not "latest") until it is live in production."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        deps = pages_api("DescribePagesDeployments", ProjectId=pid, Offset=0, Limit=50,
                         OrderBy="CreatedOn", Order="Desc")["Deployments"]
        dep = next((d for d in deps if d["DeploymentId"] == deployment_id), None)
        if dep and dep["Status"] == "Success" and dep["Env"] == "Production" and dep.get("UsedInProd"):
            return {"projectId": pid, "deploymentId": deployment_id, "createdOn": dep["CreatedOn"]}
        if dep and dep["Status"] in ("Fail", "Failed", "Error"):
            raise SystemExit(f"deployment {deployment_id} failed: {dep}")
        time.sleep(5)
    raise SystemExit(f"deployment {deployment_id} not live in production after {timeout}s")


def teo(cred):
    from tencentcloud.common.common_client import CommonClient
    from tencentcloud.common.profile.client_profile import ClientProfile

    return CommonClient("teo", "2022-09-01", cred, "", profile=ClientProfile())


def purge_prefixes(manifest, urls, timeout=300):
    """purge_prefix only the given mount URLs; never the whole host."""
    for u in urls:
        if not u.startswith(f"https://{manifest.host}/") or u == f"https://{manifest.host}/":
            raise SystemExit(f"refusing to purge {u!r}")
    cli = teo(creds.deployer())
    job = cli.call_json("CreatePurgeTask", {
        "ZoneId": manifest.zone_id, "Type": "purge_prefix", "Method": "delete", "Targets": urls,
    })["Response"]
    if job.get("FailedList"):
        raise SystemExit(f"purge rejected: {job['FailedList']}")
    job_id = job["JobId"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        tasks = cli.call_json("DescribePurgeTasks", {
            "ZoneId": manifest.zone_id, "Filters": [{"Name": "job-id", "Values": [job_id]}],
        })["Response"].get("Tasks", [])
        states = {t["Status"] for t in tasks}
        if tasks and states == {"success"}:
            return job_id
        if states & {"failed", "timeout"}:
            raise SystemExit(f"purge job {job_id} failed: {tasks}")
        time.sleep(5)
    raise SystemExit(f"purge job {job_id} not finished after {timeout}s")
