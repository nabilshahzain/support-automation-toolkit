-- health_checks.sql
-- Read-only PostgreSQL health checks for an application support engineer.
-- Written for PostgreSQL 13 and later. Nothing here changes data or settings.
--
-- Run everything:   psql -X -f sql/health_checks.sql "$DATABASE_URL"
-- Or copy one query at a time during an incident. Start with 1, 2 and 3.
--
-- Needs a role that is a member of pg_monitor (or a superuser) to see other
-- sessions' queries. Thresholds are starting points; tune them to the system.

\echo
\echo '== 1. Connection usage (are we close to max_connections?) =='
SELECT count(*)                                              AS connections,
       current_setting('max_connections')::int               AS max_connections,
       round(100.0 * count(*) / current_setting('max_connections')::int, 1) AS pct_used,
       count(*) FILTER (WHERE state = 'active')              AS active,
       count(*) FILTER (WHERE state = 'idle')                AS idle,
       count(*) FILTER (WHERE state = 'idle in transaction') AS idle_in_transaction,
       count(*) FILTER (WHERE wait_event_type = 'Lock')      AS waiting_on_lock
FROM pg_stat_activity
WHERE backend_type = 'client backend';
-- Act if pct_used > 80, or waiting_on_lock is more than a handful.

\echo
\echo '== 2. Blocking sessions (who is holding everyone up?) =='
SELECT blocked.pid                                   AS blocked_pid,
       blocked.usename                               AS blocked_user,
       date_trunc('second', now() - blocked.query_start) AS blocked_for,
       blocking.pid                                  AS blocking_pid,
       blocking.usename                              AS blocking_user,
       blocking.application_name                     AS blocking_app,
       blocking.state                                AS blocking_state,
       date_trunc('second', now() - blocking.xact_start) AS blocking_xact_age,
       left(blocking.query, 80)                      AS blocking_query
FROM pg_stat_activity AS blocked
JOIN LATERAL unnest(pg_blocking_pids(blocked.pid)) AS b(pid) ON true
JOIN pg_stat_activity AS blocking ON blocking.pid = b.pid
ORDER BY blocked.query_start;
-- The session to look at is a blocking_pid that is not itself blocked.
-- Ending it is a decision for the incident commander and the DBA:
--   SELECT pg_cancel_backend(<pid>);      -- cancels the running statement
--   SELECT pg_terminate_backend(<pid>);   -- closes the session

\echo
\echo '== 3. Long-running queries and transactions (over 1 minute) =='
SELECT pid,
       usename,
       application_name,
       state,
       date_trunc('second', now() - xact_start)  AS xact_age,
       date_trunc('second', now() - query_start) AS query_age,
       wait_event_type,
       left(query, 80)                           AS query
FROM pg_stat_activity
WHERE backend_type = 'client backend'
  AND pid <> pg_backend_pid()
  AND state <> 'idle'
  AND now() - coalesce(xact_start, query_start) > interval '1 minute'
ORDER BY coalesce(xact_start, query_start);
-- "idle in transaction" for minutes means an application or a person opened a
-- transaction and walked away. It holds locks and blocks vacuum.

\echo
\echo '== 4. Connections by user and application =='
SELECT usename, application_name, state, count(*) AS sessions
FROM pg_stat_activity
WHERE backend_type = 'client backend'
GROUP BY usename, application_name, state
ORDER BY sessions DESC
LIMIT 15;
-- A human user or a reporting tool high in this list on the primary is a risk.

\echo
\echo '== 5. Database size and cache hit ratio =='
SELECT d.datname,
       pg_size_pretty(pg_database_size(d.datname))  AS size,
       s.numbackends                                AS connections,
       s.xact_rollback                              AS rollbacks,
       s.deadlocks,
       round(100.0 * s.blks_hit / nullif(s.blks_hit + s.blks_read, 0), 2) AS cache_hit_pct
FROM pg_database AS d
JOIN pg_stat_database AS s ON s.datid = d.oid
WHERE NOT d.datistemplate
ORDER BY pg_database_size(d.datname) DESC;
-- cache_hit_pct well under 99 on a transactional database suggests memory pressure.

\echo
\echo '== 6. Largest tables =='
SELECT schemaname || '.' || relname                        AS table_name,
       pg_size_pretty(pg_total_relation_size(relid))       AS total_size,
       pg_size_pretty(pg_relation_size(relid))             AS table_size,
       pg_size_pretty(pg_indexes_size(relid))              AS index_size,
       n_live_tup                                          AS live_rows
FROM pg_stat_user_tables
ORDER BY pg_total_relation_size(relid) DESC
LIMIT 10;

\echo
\echo '== 7. Tables needing vacuum (dead rows) =='
SELECT schemaname || '.' || relname AS table_name,
       n_live_tup                   AS live_rows,
       n_dead_tup                   AS dead_rows,
       round(100.0 * n_dead_tup / nullif(n_live_tup + n_dead_tup, 0), 1) AS dead_pct,
       last_autovacuum,
       last_autoanalyze
FROM pg_stat_user_tables
WHERE n_dead_tup > 1000
ORDER BY n_dead_tup DESC
LIMIT 10;
-- dead_pct over 20 with an old last_autovacuum: check for a long transaction (query 3).

\echo
\echo '== 8. Large tables read mostly by sequential scan (missing index?) =='
SELECT schemaname || '.' || relname AS table_name,
       seq_scan,
       idx_scan,
       seq_tup_read,
       n_live_tup                   AS live_rows
FROM pg_stat_user_tables
WHERE n_live_tup > 10000
  AND seq_scan > coalesce(idx_scan, 0)
ORDER BY seq_tup_read DESC
LIMIT 10;
-- Raise with engineering as a problem record; do not create indexes during an incident.

\echo
\echo '== 9. Unused indexes larger than 10 MB =='
SELECT schemaname || '.' || relname        AS table_name,
       indexrelname                         AS index_name,
       pg_size_pretty(pg_relation_size(indexrelid)) AS index_size,
       idx_scan
FROM pg_stat_user_indexes
WHERE idx_scan = 0
  AND pg_relation_size(indexrelid) > 10 * 1024 * 1024
ORDER BY pg_relation_size(indexrelid) DESC
LIMIT 10;
-- Statistics reset on restart; check stats_reset in pg_stat_database before concluding.

\echo
\echo '== 10. Replication lag (run on the primary) =='
SELECT application_name,
       client_addr,
       state,
       sync_state,
       pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), replay_lsn)) AS replay_lag_size,
       replay_lag
FROM pg_stat_replication;
-- No rows means no replicas are connected. On a replica, use instead:
--   SELECT now() - pg_last_xact_replay_timestamp() AS replica_delay;

\echo
\echo '== 11. Transaction ID age (wraparound safety) =='
SELECT datname,
       age(datfrozenxid)                                   AS xid_age,
       round(100.0 * age(datfrozenxid) / 2000000000, 1)    AS pct_to_wraparound
FROM pg_database
ORDER BY age(datfrozenxid) DESC;
-- Over 50 percent needs a DBA's attention this week, not this quarter.
