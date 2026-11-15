# SQL health checks

Eleven read-only PostgreSQL queries that let an L2 engineer answer "is it the database?" in the first five minutes of an incident, before a DBA joins.

```bash
psql -X -f sql/health_checks.sql "$DATABASE_URL"
```

| # | Check | Question it answers | Act when |
|---|---|---|---|
| 1 | Connection usage | Are we running out of connections? | Over 80% used, or several sessions waiting on locks |
| 2 | Blocking sessions | Who is holding everyone up? | Any row during an incident |
| 3 | Long-running queries | What has been running for over a minute? | Anything on the primary that is not a known batch job |
| 4 | Connections by user | Is a person or tool using the primary heavily? | A human or reporting account near the top |
| 5 | Size and cache hit ratio | Is the database under memory pressure? | Cache hit ratio well under 99% |
| 6 | Largest tables | Where is the space going? | Capacity review |
| 7 | Dead rows | Is vacuum keeping up? | Dead rows over 20% |
| 8 | Sequential scans | Is a large table missing an index? | Raise a problem record |
| 9 | Unused indexes | What is costing writes for no benefit? | Raise a problem record |
| 10 | Replication lag | Are replicas current? | Lag over the agreed threshold |
| 11 | Transaction ID age | Any wraparound risk? | Over 50% |

## Why these exist

In [PM-005](https://github.com/nabilshahzain/incident-postmortems) a reporting query on the primary exhausted the connection pool. The first eight minutes of the response were spent restarting healthy application pods. Queries 1 to 3 would have shown the cause immediately, which is why they now open the database-errors runbook.

## Safe use

- The file only reads. The two statements that end a session appear as comments under check 2, and using them is a decision for the incident commander and the DBA.
- Use a role with `pg_monitor` membership, not a superuser.
- Do not create or drop indexes during an incident.

## Tested

Run against PostgreSQL 16 on a scratch database, including a staged lock so that check 2 returned a blocking session. Check 10 returned no rows because the test server had no replica.
