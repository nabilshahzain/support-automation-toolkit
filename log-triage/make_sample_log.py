#!/usr/bin/env python3
"""Write a synthetic application log to sample/app.log for trying log_triage.sh.

The log covers 08:00 to 12:00 on a day when a release at 09:40 makes the
rider-backend service reject order events. Everything is invented.
"""
import random
from datetime import datetime, timedelta
from pathlib import Path

rng = random.Random(7)
start = datetime(2026, 8, 10, 8, 0, 0)
release = datetime(2026, 8, 10, 9, 40, 0)
lines = []
t = start
while t < datetime(2026, 8, 10, 12, 0, 0):
    t += timedelta(seconds=rng.uniform(1, 9))
    ts = t.strftime("%Y-%m-%dT%H:%M:%S+05:30")
    req = f"{rng.randrange(16**8):08x}"
    order = rng.randrange(880000, 899999)
    roll = rng.random()
    broken = t >= release
    if broken and roll < 0.45:
        lines.append(f"{ts} ERROR [rider-backend] req={req} OrderEvent validation failed: missing required field hub_code order_id={order}")
        if rng.random() < 0.3:
            lines.append(f"{ts} WARN  [order-sync] req={req} message moved to dead-letter queue order_id={order} attempt=3")
    elif roll < 0.03:
        ms = rng.randrange(30000, 31000)
        lines.append(f"{ts} ERROR [payments] req={req} gateway timeout after {ms}ms provider=paynorth txn_id=TX{rng.randrange(10**7)}")
        lines.append(f"{ts} INFO  [api] req={req} POST /v1/payments 504 {ms}ms")
    elif roll < 0.05:
        lines.append(f"{ts} WARN  [auth] req={req} login failed for user_id={rng.randrange(1000, 99999)} reason=bad_password")
    elif roll < 0.06:
        lines.append(f"{ts} ERROR [reports] req={req} could not acquire connection from pool within 5000ms active=200 idle=0")
        lines.append(f"{ts} INFO  [api] req={req} GET /v1/reports/daily 500 5003ms")
    else:
        path = rng.choice(["/v1/orders", f"/v1/orders/{order}", "/v1/payments", "/v1/riders/nearby", "/v1/login"])
        method = "POST" if path in ("/v1/orders", "/v1/payments", "/v1/login") else "GET"
        lines.append(f"{ts} INFO  [api] req={req} {method} {path} {200 if method == 'GET' else 201} {rng.randrange(20, 400)}ms")

out = Path(__file__).resolve().parent / "sample" / "app.log"
out.write_text("\n".join(lines) + "\n")
print(f"Wrote {len(lines)} lines to {out}")
