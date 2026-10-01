"""Exercise route planning against the API's masked-secret response."""
import copy
import json
import unittest
from unittest.mock import Mock, patch

from staticpages import routes
from staticpages.manifest import Manifest


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.manifest = Manifest("www.example.com", "zone", "origin.example.com", "pages",
                                 [{"prefix": "/deck/", "status": "active"}], [],
                                 {"prefix": "/_media/", "bucket": "media", "endpoint": "oss.example.com",
                                  "region": "cn-hangzhou", "min_bytes": 20_000_000})
        patcher = patch.object(routes.creds, "media_origin", return_value=("new-key-id", "new-key-secret"))
        self.credentials = patcher.start()
        self.addCleanup(patcher.stop)
        self.current = routes.desired_media_rule(self.manifest)
        self.current["RuleId"] = "rule-media"
        self.private = self.current["Branches"][0]["Actions"][0]["ModifyOriginParameters"]["PrivateParameters"]
        self.private["SecretAccessKey"] = "masked******secret"
        self.credentials.reset_mock()
        self.cli = Mock()

    def plan(self, **kwargs):
        self.cli.call_json.return_value = {"Response": {"Rules": [copy.deepcopy(self.current)]}}
        return routes.plan(self.manifest, self.cli, **{"only": "/_media/", **kwargs})[0]

    def test_unchanged_masked_secret_is_idempotent(self):
        self.assertEqual(self.plan(), [])
        self.credentials.assert_called_once_with()

    def test_key_id_and_signing_changes_plan_a_modify(self):
        for field, old in (("AccessKeyId", "old-key-id"), ("Region", "wrong-region"),
                           ("SignatureVersion", "v2")):
            with self.subTest(field=field):
                original = self.private[field]
                self.private[field] = old
                actions = self.plan()
                self.assertEqual(len(actions), 1)
                self.assertEqual(actions[0][0], "modify")
                self.assertEqual(actions[0][2]["RuleId"], "rule-media")
                self.private[field] = original

    def test_explicit_refresh_applies_real_credentials_in_place(self):
        actions = self.plan(refresh_media_credentials=True)
        self.assertEqual(len(actions), 1)
        writer = Mock()
        with patch.object(routes.creds, "router"), patch.object(routes, "teo", return_value=writer):
            routes.apply(self.manifest, actions)
        name, params = writer.call_json.call_args.args
        self.assertEqual(name, "ModifyL7AccRule")
        self.assertEqual(params["Rule"]["RuleId"], "rule-media")
        private = params["Rule"]["Branches"][0]["Actions"][0]["ModifyOriginParameters"]["PrivateParameters"]
        self.assertEqual(private["AccessKeyId"], "new-key-id")
        self.assertEqual(private["SecretAccessKey"], "new-key-secret")
        logged = json.dumps(routes._strip_secrets(actions[0][1]))
        self.assertNotIn("new-key-id", logged)
        self.assertNotIn("new-key-secret", logged)
        self.assertIn("cn-hangzhou", logged)

    def test_filtered_namespace_does_not_read_media_credentials(self):
        actions = self.plan(only="/deck/")
        self.assertEqual(len(actions), 1)
        self.assertIn("/deck/", actions[0][1]["RuleName"])
        self.credentials.assert_not_called()

    def test_refresh_cannot_silently_skip_media_rule(self):
        with self.assertRaisesRegex(SystemExit, "requires a configured media rule"):
            self.plan(only="/deck/", refresh_media_credentials=True)
        self.cli.call_json.assert_not_called()
        self.manifest.media = {}
        with self.assertRaisesRegex(SystemExit, "requires a configured media rule"):
            self.plan(refresh_media_credentials=True)


if __name__ == "__main__":
    unittest.main()


class ImageCacheSubRuleTests(unittest.TestCase):
    def test_images_get_browser_cache_while_html_stays_no_store(self):
        import types
        rule = routes.desired_rule(types.SimpleNamespace(host="www.waytoagi.com", origin="o.example"), "/usecase-atlas/")
        branch = rule["Branches"][0]
        parent = {a["Name"]: a for a in branch["Actions"]}["ModifyResponseHeader"]
        self.assertIn("no-store", parent["ModifyResponseHeaderParameters"]["HeaderActions"][0]["Value"])
        sub = branch["SubRules"][0]["Branches"][0]
        self.assertIn("'webp'", sub["Condition"])
        self.assertNotIn("html", sub["Condition"])
        values = {h["Name"]: h for h in sub["Actions"][0]["ModifyResponseHeaderParameters"]["HeaderActions"]}
        self.assertEqual(values["Cache-Control"]["Value"], "public, max-age=604800")
