"""Offline tests for jira/sla_breach_watch.py. No network and no credentials.

Run from the repository root:  python3 -m unittest discover -s tests -v
"""
import importlib.util
import pathlib
import unittest
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("watch", ROOT / "jira" / "sla_breach_watch.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def issue(priority, hours_old):
    created = (NOW - timedelta(hours=hours_old)).strftime("%Y-%m-%dT%H:%M:%S.000%z")
    return {"key": "SUP-1", "fields": {"summary": "x", "created": created, "labels": [],
                                       "priority": {"name": priority} if priority else None}}


class AssessTests(unittest.TestCase):
    def test_within_target(self):
        self.assertEqual(watch.assess(issue("High", 2), NOW)[0], "ok")

    def test_at_risk_from_75_percent(self):
        self.assertEqual(watch.assess(issue("High", 5.9), NOW)[0], "ok")
        self.assertEqual(watch.assess(issue("High", 6), NOW)[0], "at-risk")

    def test_breached_at_target(self):
        self.assertEqual(watch.assess(issue("Highest", 4), NOW)[0], "breached")

    def test_unknown_priority_has_no_target(self):
        self.assertEqual(watch.assess(issue(None, 500), NOW)[0], "no-target")
        self.assertEqual(watch.assess(issue("Blocker", 500), NOW)[0], "no-target")

    def test_parses_jira_timestamp(self):
        parsed = watch.parse_time("2026-10-30T11:02:00.000+0530")
        self.assertEqual(parsed.utcoffset(), timedelta(hours=5, minutes=30))


class RequestShapeTests(unittest.TestCase):
    """Check the payloads sent to Jira, with the HTTP call replaced by a recorder."""

    def setUp(self):
        self.calls = []
        self.jira = watch.Jira.__new__(watch.Jira)
        pages = [{"issues": [{"key": "SUP-1"}], "nextPageToken": "abc"}, {"issues": [{"key": "SUP-2"}]}]

        def fake_call(method, path, body=None):
            self.calls.append((method, path, body))
            return pages.pop(0) if path.endswith("/search/jql") else {}
        self.jira.call = fake_call

    def test_search_follows_next_page_token(self):
        found = self.jira.search("project = SUP")
        self.assertEqual([i["key"] for i in found], ["SUP-1", "SUP-2"])
        self.assertEqual(self.calls[0][1], "/rest/api/3/search/jql")
        self.assertNotIn("nextPageToken", self.calls[0][2])
        self.assertEqual(self.calls[1][2]["nextPageToken"], "abc")
        self.assertIn("priority", self.calls[0][2]["fields"])

    def test_label_and_comment_payloads(self):
        self.jira.add_label("SUP-9", "sla-breached")
        self.jira.add_comment("SUP-9", "hello")
        self.assertEqual(self.calls[0], ("PUT", "/rest/api/3/issue/SUP-9",
                                         {"update": {"labels": [{"add": "sla-breached"}]}}))
        method, path, body = self.calls[1]
        self.assertEqual((method, path), ("POST", "/rest/api/3/issue/SUP-9/comment"))
        self.assertEqual(body["body"]["type"], "doc")
        self.assertEqual(body["body"]["content"][0]["content"][0]["text"], "hello")


if __name__ == "__main__":
    unittest.main()
