"""Execute the real workflow's Bash with a harmless argv-recording Python stub."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from staticpages.manifest import ROOT


class RoutesWorkflowTest(unittest.TestCase):
    def test_inputs_remain_literal_arguments(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/routes.yml").read_text())
        step = next(s for s in workflow["jobs"]["routes"]["steps"]
                    if "TENCENTCLOUD_ROUTER_SECRET_ID" in s.get("env", {}))
        cases = [
            ("plan", "", False),
            ("apply", "/_media/", True),
            ("plan", "--refresh-media-credentials", False),
            ("plan", '/_media/; touch INJECTED; $(touch SUBSTITUTED) `touch BACKTICKS`\n"quoted text"', False),
            ("plan; touch ACTION_INJECTED", "/_media/", False),
        ]
        for action, only, refresh in cases:
            with self.subTest(action=action, only=only), tempfile.TemporaryDirectory() as tmp:
                work = Path(tmp)
                python = work / "python"
                python.write_text('#!/bin/sh\nprintf \'%s\\0\' "$@" > "$ARGV_CAPTURE"\n')
                python.chmod(0o755)
                capture = work / "argv"
                env = {"PATH": f"{work}{os.pathsep}/usr/bin:/bin", "ARGV_CAPTURE": str(capture),
                       "ROUTES_ACTION": action, "ROUTES_ONLY": only,
                       "ROUTES_REFRESH_MEDIA_CREDENTIALS": str(refresh).lower()}
                subprocess.run(["bash", "-e", "-c", step["run"]], env=env, cwd=work, check=True)
                expected = ["-m", "staticpages", "routes", action]
                if only:
                    expected.append(f"--only={only}")
                if refresh:
                    expected.append("--refresh-media-credentials")
                self.assertEqual(capture.read_bytes().decode().split("\0")[:-1], expected)
                self.assertEqual({p.name for p in work.iterdir()}, {"python", "argv"})


if __name__ == "__main__":
    unittest.main()
