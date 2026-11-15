#!/usr/bin/env bash
# log_triage.sh - first-look summary of an application log during an incident.
#
# Answers, in a few seconds: how many errors, since when, which service,
# and what are the most common error messages once IDs and numbers are
# stripped out.
#
# Expected line format (ISO timestamp, level, [service], message):
#   2026-08-10T09:41:07+05:30 ERROR [rider-backend] req=ab12 message text
#
# Usage:
#   log_triage.sh [-n TOP] [-s SINCE] [-u UNTIL] [-l LEVELS] FILE [FILE...]
#
#   -n TOP     number of rows in each "top" list (default 10)
#   -s SINCE   only lines at or after this time, e.g. 2026-08-10T09:30
#   -u UNTIL   only lines before this time,      e.g. 2026-08-10T10:30
#   -l LEVELS  levels counted as problems (default "ERROR|FATAL|CRITICAL")
#   -h         show this help
#
# Files ending in .gz are read with gzip. Read-only: nothing is modified.

set -euo pipefail

TOP=10
SINCE=""
UNTIL=""
LEVELS="ERROR|FATAL|CRITICAL"

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }

while getopts ":n:s:u:l:h" opt; do
  case "$opt" in
    n) TOP="$OPTARG" ;;
    s) SINCE="$OPTARG" ;;
    u) UNTIL="$OPTARG" ;;
    l) LEVELS="$OPTARG" ;;
    h) usage; exit 0 ;;
    *) echo "Unknown or incomplete option: -$OPTARG" >&2; usage >&2; exit 2 ;;
  esac
done
shift $((OPTIND - 1))

if [ "$#" -eq 0 ]; then
  echo "error: give at least one log file" >&2
  usage >&2
  exit 2
fi
case "$TOP" in ''|*[!0-9]*) echo "error: -n needs a whole number" >&2; exit 2 ;; esac

for f in "$@"; do
  [ -r "$f" ] || { echo "error: cannot read $f" >&2; exit 1; }
done

read_logs() {
  for f in "$@"; do
    case "$f" in
      *.gz) gzip -dc -- "$f" ;;
      *)    cat -- "$f" ;;
    esac
  done
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# One awk pass writes small work files; sort and uniq do the ranking.
read_logs "$@" | awk -v since="$SINCE" -v until="$UNTIL" -v levels="^(${LEVELS})$" -v out="$TMP" '
  # keep only lines that start with an ISO date
  $1 !~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T/ { skipped++; next }
  since != "" && $1 <  since { next }
  until != "" && $1 >= until { next }
  {
    total++
    if (first == "") first = $1
    last = $1
    level[$2]++

    # HTTP access lines: "... METHOD /path STATUS 123ms"
    for (i = 4; i <= NF - 2; i++) {
      if ($i ~ /^(GET|POST|PUT|PATCH|DELETE)$/ && $(i + 2) ~ /^5[0-9][0-9]$/) {
        path = $(i + 1); gsub(/\/[0-9]+/, "/N", path)
        print $i " " path " " $(i + 2) > (out "/http5xx")
      }
    }

    if ($2 !~ levels) next
    problems++
    print substr($1, 1, 13) > (out "/hours")
    svc = $3; gsub(/[\[\]]/, "", svc)
    print svc > (out "/services")

    # signature: the message with volatile values removed
    sig = $0
    sub(/^[^ ]+ +[^ ]+ +/, "", sig)                           # drop time and level
    gsub(/=[A-Za-z0-9_.-]*[0-9][A-Za-z0-9_.-]*/, "=*", sig)   # key=value holding a digit
    gsub(/[0-9]+/, "N", sig)                                  # any other number
    print sig > (out "/signatures")
    print sig "\t" $1 > (out "/sig_times")
  }
  END {
    printf "%d\t%d\t%s\t%s\t%d\n", total, problems, first, last, skipped > (out "/totals")
    for (l in level) printf "%s\t%d\n", l, level[l] > (out "/levels")
  }
'

IFS=$'\t' read -r TOTAL PROBLEMS FIRST LAST SKIPPED < "$TMP/totals"

if [ "$TOTAL" -eq 0 ]; then
  echo "No log lines matched (check the file format and the -s / -u range)."
  exit 0
fi

echo "LOG TRIAGE SUMMARY"
echo "=================="
echo "Files:        $*"
echo "Time range:   $FIRST  to  $LAST"
echo "Lines read:   $TOTAL   (ignored, no timestamp: $SKIPPED)"
echo "Problem lines ($LEVELS): $PROBLEMS"
echo

echo "Lines by level"
sort -t "$(printf '\t')" -k2,2nr "$TMP/levels" | awk -F '\t' '{ printf "  %-9s %8d\n", $1, $2 }'
echo

if [ "$PROBLEMS" -eq 0 ]; then
  echo "No problem lines in this range."
  exit 0
fi

echo "Problem lines per hour"
sort "$TMP/hours" | uniq -c | awk '
  { n[NR] = $1; h[NR] = $2; if ($1 > max) max = $1 }
  END {
    for (i = 1; i <= NR; i++) {
      bar = ""; len = int(n[i] * 40 / max); if (len < 1) len = 1
      for (j = 0; j < len; j++) bar = bar "#"
      printf "  %s:00 %7d  %s\n", h[i], n[i], bar
    }
  }'
echo

echo "Problem lines by service"
sort "$TMP/services" | uniq -c | sort -rn | head -n "$TOP" | awk '{ printf "  %7d  %s\n", $1, $2 }'
echo

echo "Top $TOP error signatures (IDs and numbers replaced)"
sort "$TMP/signatures" | uniq -c | sort -rn | head -n "$TOP" > "$TMP/top"
awk -F '\t' '
  NR == FNR { if (!($1 in firstseen)) firstseen[$1] = $2; lastseen[$1] = $2; next }
  {
    count = $1; sig = $0
    sub(/^ *[0-9]+ /, "", sig)
    printf "  %7d  %s\n           first %s   last %s\n", count, sig, firstseen[sig], lastseen[sig]
  }' "$TMP/sig_times" FS=' ' "$TMP/top"
echo

if [ -s "$TMP/http5xx" ]; then
  echo "HTTP 5xx responses by endpoint"
  sort "$TMP/http5xx" | uniq -c | sort -rn | head -n "$TOP" | awk '{ printf "  %7d  %s %s -> %s\n", $1, $2, $3, $4 }'
  echo
fi

echo "Next step: take the top signature and its first-seen time, and compare"
echo "that time with the change calendar."
