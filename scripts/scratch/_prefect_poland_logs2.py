"""Dump logs for specific failed poland flow runs."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path.home() / ".prefect" / "prefect.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

run_ids = [
    "01a017f6-8d40-7788-87ca-3174f1b8fa28",  # angelic-sheep
    "01a015c0-44af-7532-b5ab-aca5c77afd41",  # smooth-lyrebird
    "01a015c0-44af-7d35-8905-b195d3db727e",  # elite-hyrax
]

for run_id in run_ids:
    cur.execute("SELECT name, created, start_time, end_time FROM flow_run WHERE id=?", (run_id,))
    run = cur.fetchone()
    print(f"\n{'='*70}\n{dict(run)}\n{'='*70}")

    cur.execute(
        "SELECT type, name, timestamp, message FROM flow_run_state WHERE flow_run_id=? ORDER BY timestamp",
        (run_id,),
    )
    for s in cur.fetchall():
        print("STATE:", dict(s))

    cur.execute("SELECT id, name FROM task_run WHERE flow_run_id=?", (run_id,))
    for t in cur.fetchall():
        print("TASK:", dict(t))
        cur.execute(
            "SELECT level, timestamp, message FROM log WHERE task_run_id=? OR flow_run_id=? ORDER BY timestamp",
            (t["id"], run_id),
        )
        rows = cur.fetchall()
        print(f"  log rows: {len(rows)}")
        for row in rows:
            msg = row["message"]
            print(f"  [{row['level']}] {row['timestamp']} {msg[:1000]}")

    cur.execute(
        "SELECT level, timestamp, message FROM log WHERE flow_run_id=? ORDER BY timestamp",
        (run_id,),
    )
    flow_logs = cur.fetchall()
    print(f"flow-level logs: {len(flow_logs)}")
    for row in flow_logs:
        print(f"  [{row['level']}] {row['timestamp']} {row['message'][:1000]}")

conn.close()
