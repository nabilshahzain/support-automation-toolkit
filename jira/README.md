# Jira SLA breach watch

Labels open Jira issues that are at 75% of their resolution target (`sla-at-risk`) or past it (`sla-breached`), and adds one comment to each newly flagged issue.

## Why

A lead cannot watch every ticket's age. A saved filter on the two labels gives a short list to walk through at stand-up, and the comment tells the assignee before the target is missed instead of after.

## Try it without Jira

```bash
python3 jira/sla_breach_watch.py --from-file jira/sample_issues.json --now 2026-10-31T12:00:00+05:30
```

## Run it against Jira Cloud

1. Create an API token at id.atlassian.com under Security.
2. Set three environment variables. Keep the token out of the repository and out of shell history files.
   ```bash
   export JIRA_BASE_URL=https://your-site.atlassian.net
   export JIRA_EMAIL=you@example.com
   export JIRA_API_TOKEN=...
   ```
3. Dry run first; it only reads.
   ```bash
   python3 jira/sla_breach_watch.py --project SUP
   ```
4. When the output looks right, add `--apply`.
5. Schedule it every 15 minutes with cron or a CI job, using a service account with permission to edit and comment on issues in that one project.

## Behaviour

| Situation | Action |
|---|---|
| Age under 75% of target | None |
| Age 75% to 100% of target, not yet labelled | Add `sla-at-risk`, comment once |
| Age over target, not yet labelled breached | Add `sla-breached`, comment once |
| Already carries the relevant label | None, so repeated runs do not spam the ticket |
| Priority has no target configured | Counted and reported; no action |

Targets are set in `TARGET_HOURS` at the top of the script: Highest 4 h, High 8 h, Medium 24 h, Low and Lowest 72 h.

## Limits

- Age is calendar hours since creation. There is no business-hours calendar and no pause while waiting for the customer.
- Jira Service Management projects have built-in SLA fields that are more precise. Use those where available; this script suits Jira Software projects used as a support queue.
- The write path (`--apply`) is covered by unit tests on the request payloads and has not been run against a live Jira site from this repository. Run a dry run on your own site first.
