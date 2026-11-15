#!/usr/bin/env python3
"""Compute MTTR and SLA breaches from a ticket CSV export.

Usage:
  python3 sla_report.py tickets.csv
  python3 sla_report.py tickets.csv --from 2026-08-01 --to 2026-08-31
  python3 sla_report.py tickets.csv --breaches-csv breaches.csv
  python3 sla_report.py tickets.csv --fail-under 95      # exit code 1 if below

Required columns: ticket_id, created_at, priority, category,
resolution_hours, sla_target_hours. Open tickets have an empty
resolution_hours and are counted separately; if they are already past their
target they are reported as breaching even though they are not yet resolved.

Standard library only.
"""
import argparse
import csv
import statistics
import sys
from collections import defaultdict
from datetime import datetime

REQUIRED = ["ticket_id", "created_at", "priority", "category",
            "resolution_hours", "sla_target_hours"]


def parse_args():
    p = argparse.ArgumentParser(description="MTTR and SLA breach report from a ticket CSV")
    p.add_argument("csv_path")
    p.add_argument("--from", dest="date_from", help="include tickets created on or after YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", help="include tickets created on or before YYYY-MM-DD")
    p.add_argument("--as-of", help="'now' for ageing open tickets, YYYY-MM-DDTHH:MM (default: latest created_at in the file)")
    p.add_argument("--top", type=int, default=10, help="rows in the worst-breaches list (default 10)")
    p.add_argument("--breaches-csv", help="write every breached ticket to this CSV file")
    p.add_argument("--fail-under", type=float, help="exit with code 1 if overall SLA compliance is below this percentage")
    return p.parse_args()


def load(path):
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            sys.exit(f"error: {path} is missing columns: {', '.join(missing)}")
        tickets, bad = [], 0
        for row in reader:
            try:
                row["_created"] = datetime.fromisoformat(row["created_at"])
                row["_target"] = float(row["sla_target_hours"])
                row["_hours"] = float(row["resolution_hours"]) if row["resolution_hours"] else None
            except ValueError:
                bad += 1
                continue
            tickets.append(row)
    return tickets, bad


def pct(part, whole):
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def percentile(values, q):
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(q * (len(ordered) - 1))))
    return ordered[index]


def num(value):
    return "n/a" if value is None else f"{value:.1f}"


def summarise(group):
    resolved = [t for t in group if t["_hours"] is not None]
    hours = [t["_hours"] for t in resolved]
    breached = [t for t in resolved if t["_hours"] > t["_target"]]
    return {
        "created": len(group), "resolved": len(resolved),
        "open": len(group) - len(resolved),
        "mean": statistics.fmean(hours) if hours else None,
        "median": statistics.median(hours) if hours else None,
        "p90": percentile(hours, 0.9),
        "breached": len(breached),
        "compliance": 100 * (len(resolved) - len(breached)) / len(resolved) if resolved else None,
    }


def table(header, rows):
    print("| " + " | ".join(header) + " |")
    print("|" + "|".join("---" if i == 0 else "---:" for i in range(len(header))) + "|")
    for row in rows:
        print("| " + " | ".join(str(c) for c in row) + " |")
    print()


def metric_row(label, s):
    return [label, s["created"], s["resolved"], num(s["mean"]), num(s["median"]), num(s["p90"]),
            s["breached"], "n/a" if s["compliance"] is None else f"{s['compliance']:.1f}%"]


def main():
    args = parse_args()
    tickets, bad = load(args.csv_path)
    if args.date_from:
        start = datetime.fromisoformat(args.date_from)
        tickets = [t for t in tickets if t["_created"] >= start]
    if args.date_to:
        end = datetime.fromisoformat(args.date_to).replace(hour=23, minute=59, second=59)
        tickets = [t for t in tickets if t["_created"] <= end]
    if not tickets:
        sys.exit("error: no tickets in the selected range")

    if args.as_of == "now":
        as_of = datetime.now()
    elif args.as_of:
        as_of = datetime.fromisoformat(args.as_of)
    else:
        as_of = max(t["_created"] for t in tickets)

    first = min(t["_created"] for t in tickets).date()
    last = max(t["_created"] for t in tickets).date()
    overall = summarise(tickets)
    print(f"# SLA and MTTR report\n")
    print(f"Tickets created {first} to {last}: {len(tickets)}"
          + (f" ({bad} unreadable rows skipped)" if bad else "") + "\n")

    header = ["", "Created", "Resolved", "MTTR mean (h)", "Median (h)", "P90 (h)", "Breaches", "SLA met"]
    print("## By priority\n")
    by_priority = defaultdict(list)
    for t in tickets:
        by_priority[t["priority"]].append(t)
    rows = [metric_row(p, summarise(by_priority[p])) for p in sorted(by_priority)]
    rows.append(metric_row("All", overall))
    table(header, rows)

    print("## By month\n")
    by_month = defaultdict(list)
    for t in tickets:
        by_month[t["_created"].strftime("%Y-%m")].append(t)
    table(header, [metric_row(m, summarise(by_month[m])) for m in sorted(by_month)])

    breached = [t for t in tickets if t["_hours"] is not None and t["_hours"] > t["_target"]]
    print("## Where the breaches come from\n")
    by_category = defaultdict(lambda: [0, 0])
    for t in tickets:
        if t["_hours"] is not None:
            by_category[t["category"]][0] += 1
    for t in breached:
        by_category[t["category"]][1] += 1
    rows = sorted(by_category.items(), key=lambda kv: -kv[1][1])
    table(["Category", "Resolved", "Breaches", "Breach rate", "Share of all breaches"],
          [[c, r, b, pct(b, r), pct(b, len(breached))] for c, (r, b) in rows])

    print(f"## {min(args.top, len(breached))} worst breaches (hours over target)\n")
    worst = sorted(breached, key=lambda t: t["_hours"] - t["_target"], reverse=True)[:args.top]
    table(["Ticket", "Priority", "Category", "Created", "Resolved in (h)", "Target (h)", "Over by (h)"],
          [[t["ticket_id"], t["priority"], t["category"], t["created_at"][:10],
            f"{t['_hours']:.1f}", f"{t['_target']:g}", f"{t['_hours'] - t['_target']:.1f}"] for t in worst])

    open_tickets = [t for t in tickets if t["_hours"] is None]
    overdue = [t for t in open_tickets
               if (as_of - t["_created"]).total_seconds() / 3600 > t["_target"]]
    print("## Open tickets\n")
    print(f"As of {as_of:%Y-%m-%d %H:%M}: {len(open_tickets)} open, of which {len(overdue)} are already "
          f"past their target. These are not in the compliance figure above until they are resolved.\n")

    if args.breaches_csv:
        with open(args.breaches_csv, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(["ticket_id", "priority", "category", "created_at",
                             "resolution_hours", "sla_target_hours", "hours_over"])
            for t in sorted(breached, key=lambda t: t["created_at"]):
                writer.writerow([t["ticket_id"], t["priority"], t["category"], t["created_at"],
                                 t["resolution_hours"], t["sla_target_hours"],
                                 round(t["_hours"] - t["_target"], 2)])
        print(f"Wrote {len(breached)} breached tickets to {args.breaches_csv}\n")

    if args.fail_under is not None and overall["compliance"] is not None \
            and overall["compliance"] < args.fail_under:
        print(f"FAIL: SLA compliance {overall['compliance']:.1f}% is below {args.fail_under:g}%", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
