#!/usr/bin/env python3
"""Flag Jira tickets that are close to, or past, their resolution target.

For every open issue returned by a JQL query, compare its age with the target
for its priority. Issues at 75% of the target get the label `sla-at-risk`;
issues past it get `sla-breached`. Each newly flagged issue also gets one
comment, so a lead watching the queue is told once and only once.

Dry run is the default. Nothing is written to Jira without --apply.

  # offline, against the bundled sample (no credentials needed)
  python3 sla_breach_watch.py --from-file sample_issues.json --now 2026-10-31T12:00:00+05:30

  # against Jira Cloud: see what would happen
  export JIRA_BASE_URL=https://your-site.atlassian.net
  export JIRA_EMAIL=you@example.com
  export JIRA_API_TOKEN=...        # never commit this
  python3 sla_breach_watch.py --project SUP

  # and then do it
  python3 sla_breach_watch.py --project SUP --apply

Uses Jira Cloud REST API v3 (POST /rest/api/3/search/jql). Standard library only.

Limits: age is measured in calendar hours from creation, with no business-hours
calendar and no pause for "waiting for customer". Jira Service Management's
built-in SLA fields are more precise where they are available; this script is
for projects that do not have them.
"""
import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

# Resolution targets in hours, by Jira priority name. Edit to match your scheme.
TARGET_HOURS = {"Highest": 4, "High": 8, "Medium": 24, "Low": 72, "Lowest": 72}
AT_RISK_FRACTION = 0.75
LABEL_AT_RISK = "sla-at-risk"
LABEL_BREACHED = "sla-breached"
FIELDS = ["summary", "priority", "created", "labels", "assignee", "status"]


def parse_args():
    p = argparse.ArgumentParser(description="Label Jira issues that are near or past their SLA target")
    p.add_argument("--project", help="Jira project key, e.g. SUP")
    p.add_argument("--jql", help="custom JQL; overrides --project. Must be bounded (include a project or date filter)")
    p.add_argument("--days", type=int, default=30, help="look at issues created in the last N days (default 30)")
    p.add_argument("--apply", action="store_true", help="write labels and comments to Jira (default is a dry run)")
    p.add_argument("--from-file", help="read issues from a JSON file instead of calling Jira")
    p.add_argument("--now", help="ISO time to treat as 'now' (for testing)")
    args = p.parse_args()
    if not args.from_file and not (args.project or args.jql):
        p.error("give --project or --jql (or --from-file for an offline run)")
    if args.from_file and args.apply:
        p.error("--apply cannot be used with --from-file")
    return args


class Jira:
    def __init__(self):
        try:
            self.base = os.environ["JIRA_BASE_URL"].rstrip("/")
            user, token = os.environ["JIRA_EMAIL"], os.environ["JIRA_API_TOKEN"]
        except KeyError as missing:
            sys.exit(f"error: environment variable {missing} is not set")
        if not self.base.startswith("https://"):
            sys.exit("error: JIRA_BASE_URL must start with https://")
        self.auth = "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()

    def call(self, method, path, body=None):
        request = urllib.request.Request(
            self.base + path, method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": self.auth, "Accept": "application/json",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as err:
            detail = err.read().decode(errors="replace")[:300]
            sys.exit(f"error: Jira returned {err.code} for {method} {path}: {detail}")
        except urllib.error.URLError as err:
            sys.exit(f"error: could not reach Jira: {err.reason}")

    def search(self, jql):
        issues, token = [], None
        while True:
            body = {"jql": jql, "fields": FIELDS, "maxResults": 100}
            if token:
                body["nextPageToken"] = token
            page = self.call("POST", "/rest/api/3/search/jql", body)
            issues.extend(page.get("issues", []))
            token = page.get("nextPageToken")
            if not token:
                return issues

    def add_label(self, key, label):
        self.call("PUT", f"/rest/api/3/issue/{key}", {"update": {"labels": [{"add": label}]}})

    def add_comment(self, key, text):
        self.call("POST", f"/rest/api/3/issue/{key}/comment", {"body": {
            "type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}})


def parse_time(value):
    """Jira returns 2026-10-30T11:02:00.000+0530; also accept plain ISO 8601."""
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    return datetime.fromisoformat(value)


def assess(issue, now):
    """Return (state, age_hours, target_hours) where state is ok, at-risk, breached or no-target."""
    fields = issue["fields"]
    priority = (fields.get("priority") or {}).get("name")
    target = TARGET_HOURS.get(priority)
    age = (now - parse_time(fields["created"])).total_seconds() / 3600
    if target is None:
        return "no-target", age, None
    if age >= target:
        return "breached", age, target
    if age >= AT_RISK_FRACTION * target:
        return "at-risk", age, target
    return "ok", age, target


def main():
    args = parse_args()
    now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
    if now.tzinfo is None:
        sys.exit("error: --now needs a UTC offset, e.g. 2026-10-31T12:00:00+05:30")

    jira = None
    if args.from_file:
        with open(args.from_file) as fh:
            issues = json.load(fh)["issues"]
    else:
        jira = Jira()
        jql = args.jql or (f'project = "{args.project}" AND statusCategory != Done '
                           f"AND created >= -{args.days}d ORDER BY created ASC")
        issues = jira.search(jql)

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"[{mode}] {len(issues)} open issues checked at {now:%Y-%m-%d %H:%M %z}\n")
    counts = {"ok": 0, "at-risk": 0, "breached": 0, "no-target": 0}
    actions = 0

    for issue in issues:
        key, fields = issue["key"], issue["fields"]
        state, age, target = assess(issue, now)
        counts[state] += 1
        if state in ("ok", "no-target"):
            continue
        label = LABEL_BREACHED if state == "breached" else LABEL_AT_RISK
        priority = fields["priority"]["name"]
        assignee = (fields.get("assignee") or {}).get("displayName", "unassigned")
        already = label in (fields.get("labels") or [])
        print(f"{key:<10} {state.upper():<9} {priority:<8} age {age:6.1f}h / target {target}h  "
              f"{assignee:<12} {fields['summary'][:50]}")
        if already:
            print(f"{'':<10} already labelled {label}; no action")
            continue
        actions += 1
        if state == "breached":
            comment = (f"SLA breached: this {priority} ticket is {age:.0f} hours old against a "
                       f"{target}-hour target. Team lead, please review today.")
        else:
            comment = (f"SLA at risk: this {priority} ticket is {age:.0f} hours old and will breach its "
                       f"{target}-hour target in {target - age:.1f} hours. Escalate now if it is blocked.")
        if args.apply:
            jira.add_label(key, label)
            jira.add_comment(key, comment)
            print(f"{'':<10} labelled {label} and commented")
        else:
            print(f"{'':<10} would add label {label} and comment: {comment}")

    print(f"\nSummary: {counts['breached']} breached, {counts['at-risk']} at risk, {counts['ok']} within target, "
          f"{counts['no-target']} with no target for their priority.")
    print(f"{actions} issue(s) {'updated' if args.apply else 'would be updated'}.")
    if not args.apply and actions:
        print("Run again with --apply to write these changes to Jira.")


if __name__ == "__main__":
    main()
