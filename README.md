# Support Automation Toolkit

Four small tools that take routine work out of an application support team's day. Each one exists because of a specific operational problem, runs against bundled sample data, and uses only what is already on a support engineer's machine: Bash, awk, Python 3 and `psql`.

> All sample data is synthetic and the company, "Kestrel Logistics", is fictional.

| Tool | Problem it solves | Language |
|---|---|---|
| [`log-triage/log_triage.sh`](log-triage/log_triage.sh) | In the first minutes of an incident nobody knows which error matters. This ranks error messages with IDs stripped out and shows when each first appeared. | Bash, awk |
| [`sql/health_checks.sql`](sql/health_checks.sql) | "Is it the database?" Eleven read-only PostgreSQL checks, starting with connections, blocking sessions and long-running queries. | SQL |
| [`kpi/sla_report.py`](kpi/sla_report.py) | The monthly SLA report took half a day in a spreadsheet. This produces MTTR, breach counts and breach drivers from a ticket export in a second. | Python |
| [`jira/sla_breach_watch.py`](jira/sla_breach_watch.py) | Breaches were found after the fact. This labels and comments on tickets at 75% of their target. | Python, Jira Cloud REST API |

## Quick start

```bash
git clone https://github.com/nabilshahzain/support-automation-toolkit.git
cd support-automation-toolkit
bash tests/smoke.sh          # runs everything against sample data; no network needed
```

## 1. Log triage

```bash
./log-triage/log_triage.sh log-triage/sample/app.log
./log-triage/log_triage.sh -s 2026-08-10T09:30 -u 2026-08-10T10:30 -n 5 app.log app.log.1.gz
```

Output on the sample log (shortened):

```
LOG TRIAGE SUMMARY
==================
Files:        log-triage/sample/app.log
Time range:   2026-08-10T08:00:03+05:30  to  2026-08-10T12:00:01+05:30
Lines read:   3158   (ignored, no timestamp: 0)
Problem lines (ERROR|FATAL|CRITICAL): 776

Top 3 error signatures (IDs and numbers replaced)
      731  [rider-backend] req=* OrderEvent validation failed: missing required field hub_code order_id=*
           first 2026-08-10T09:40:10+05:30   last 2026-08-10T12:00:01+05:30
       32  [payments] req=* gateway timeout after Nms provider=paynorth txn_id=*
           first 2026-08-10T08:01:25+05:30   last 2026-08-10T09:37:26+05:30
       13  [reports] req=* could not acquire connection from pool within Nms active=* idle=*
           first 2026-08-10T08:00:31+05:30   last 2026-08-10T09:37:55+05:30
```

The top signature and its first-seen time (09:40) are the two facts that would have shortened [PM-001](https://github.com/nabilshahzain/incident-postmortems) by about two hours.

## 2. SQL health checks

```bash
psql -X -f sql/health_checks.sql "$DATABASE_URL"
```

Details, thresholds and safe-use notes are in [sql/README.md](sql/README.md).

## 3. SLA and MTTR report

```bash
python3 kpi/sla_report.py kpi/sample_tickets.csv
python3 kpi/sla_report.py tickets.csv --from 2026-08-01 --to 2026-08-31 --breaches-csv breaches.csv
python3 kpi/sla_report.py tickets.csv --fail-under 95     # exit code 1 if below target
```

Output on the sample data (first table):

|  | Created | Resolved | MTTR mean (h) | Median (h) | P90 (h) | Breaches | SLA met |
|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | 79 | 78 | 1.7 | 1.2 | 2.9 | 5 | 93.6% |
| P2 | 268 | 263 | 4.3 | 2.8 | 7.6 | 21 | 92.0% |
| P3 | 801 | 791 | 12.2 | 8.4 | 19.9 | 46 | 94.2% |
| P4 | 478 | 469 | 33.8 | 23.9 | 60.5 | 35 | 92.5% |
| All | 1626 | 1601 | 16.7 | 9.3 | 34.6 | 107 | 93.3% |

It also reports by month, breach rate by category, the worst individual breaches, and open tickets already past their target. The report shows the median and 90th percentile next to the mean, because a few very old tickets distort a mean.

## 4. Jira SLA breach watch

```bash
python3 jira/sla_breach_watch.py --from-file jira/sample_issues.json --now 2026-10-31T12:00:00+05:30
python3 jira/sla_breach_watch.py --project SUP            # dry run against Jira Cloud
python3 jira/sla_breach_watch.py --project SUP --apply    # write labels and comments
```

Dry run is the default. Setup and behaviour are in [jira/README.md](jira/README.md).

## Design choices

- **Read-only or dry-run by default.** Anything that writes needs an explicit flag.
- **No dependencies to install.** A tool that needs a virtual environment does not get used at 03:00.
- **Sample data in the repository**, so every tool can be tried and tested without access to a real system.
- **No secrets in code.** Credentials come from environment variables.
- **Plain output** that can be pasted into a ticket or an incident channel.

## What has been tested

| Tool | How |
|---|---|
| Log triage | Run on the bundled sample with mawk 1.3.4; uses only POSIX awk features |
| SQL health checks | Run on PostgreSQL 16 with a staged lock; replication check untested (no replica) |
| SLA report | Run on the bundled 1,626-ticket sample |
| Jira watch | Offline run plus unit tests of the request payloads; `--apply` not run against a live Jira site |

## Repository layout

```
log-triage/   log_triage.sh, sample log and its generator
sql/          health_checks.sql and notes
kpi/          sla_report.py and sample tickets
jira/         sla_breach_watch.py, sample issues and notes
tests/        smoke.sh and unit tests
```

## Related repositories

- [support-ops-dashboard](https://github.com/nabilshahzain/support-ops-dashboard): the same ticket data, visualised.
- [incident-postmortems](https://github.com/nabilshahzain/incident-postmortems): the incidents these tools respond to.
- [support-ops-handbook](https://github.com/nabilshahzain/support-ops-handbook): the runbooks that reference them.

## Author

Mohammed Nabiuddin Shahzain. Application and product support manager. [LinkedIn](https://www.linkedin.com/in/nabiuddinzain)

Released under the [MIT License](LICENSE).
