#!/usr/bin/env bash
# Run every tool against its bundled sample data. No network, no database.
# Usage: bash tests/smoke.sh   (from the repository root)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "1/4 log triage"
out="$(./log-triage/log_triage.sh -n 3 log-triage/sample/app.log)"
echo "$out" | grep -q "missing required field hub_code" || { echo "FAIL: top signature missing"; exit 1; }

echo "2/4 SLA report"
out="$(python3 kpi/sla_report.py kpi/sample_tickets.csv)"
echo "$out" | grep -q "## By priority" || { echo "FAIL: report sections missing"; exit 1; }
if python3 kpi/sla_report.py kpi/sample_tickets.csv --fail-under 99 >/dev/null 2>&1; then
  echo "FAIL: --fail-under should exit non-zero"; exit 1
fi

echo "3/4 Jira watch (offline)"
out="$(python3 jira/sla_breach_watch.py --from-file jira/sample_issues.json --now 2026-10-31T12:00:00+05:30)"
echo "$out" | grep -q "3 breached, 2 at risk" || { echo "FAIL: unexpected Jira summary"; exit 1; }

echo "4/4 unit tests"
python3 -m unittest discover -s tests -q

echo "All checks passed."
