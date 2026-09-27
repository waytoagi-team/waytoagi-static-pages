"""Post a deploy record to a Feishu custom-bot webhook (FEISHU_WEBHOOK), if configured."""
import json
import os
import urllib.request


def send(lines):
    url = os.environ.get("FEISHU_WEBHOOK")
    if not url:
        print("FEISHU_WEBHOOK not set; skipping notification")
        return
    body = json.dumps({"msg_type": "text", "content": {"text": "\n".join(lines)}}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"feishu: {resp.status}")
