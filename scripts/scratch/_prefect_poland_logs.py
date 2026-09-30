"""One-off: dump recent poland-weekday-poll logs from local Prefect DB."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path.home() / ".prefect" / "prefect.db"
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute(
    """
    SELECT fr.id, fr.name, fr.created, fr.start_time, fr.end_time, d.name AS deployment
    FROM flow_run fr
    JOIN deployment d ON d.id = fr.deployment_id
    WHERE d.name LIKE '%poland%'
    ORDER BY fr.created DESC
    LIMIT 8
    """
)
runs = cur.fetchall()
print("=== Recent poland runs ===")
for r in runs:
    print(dict(r))

for run in runs[:3]:
    run_id = run["id"]
    print(f"\n{'='*60}\nRUN {run['name']} ({run['created']})\n{'='*60}")

    cur.execute(
        """
        SELECT type, name, timestamp, message
        FROM flow_run_state
        WHERE flow_run_id = ?
        ORDER BY timestamp DESC
        LIMIT 5
        """,
        (run_id,),
    )
    for s in cur.fetchall():
        print("STATE:", dict(s))

    cur.execute(
        """
        SELECT id, name, start_time, end_time
        FROM task_run
        WHERE flow_run_id = ?
        ORDER BY created DESC
        """,
        (run_id,),
    )
    tasks = cur.fetchall()
    for t in tasks:
        print("TASK:", dict(t))
        cur.execute(
            """
            SELECT level, timestamp, message
            FROM log
            WHERE task_run_id = ?
            ORDER BY timestamp
            """,
            (t["id"],),
        )
        logs = cur.fetchall()
        if logs:
            print("--- logs ---")
            for row in logs:
                msg = row["message"]
                if len(msg) > 800:
                    msg = msg[:800] + "..."
                print(f"[{row['level']}] {row['timestamp']} {msg}")

conn.close()
