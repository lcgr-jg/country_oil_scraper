import sqlite3
from pathlib import Path

c = sqlite3.connect(Path.home() / ".prefect" / "prefect.db")
print("=== poland deployments ===")
for r in c.execute(
    "SELECT id, name, created FROM deployment WHERE name LIKE '%poland%' ORDER BY created"
):
    print(r)

print("\n=== hungary deployments ===")
for r in c.execute(
    "SELECT id, name, created FROM deployment WHERE name LIKE '%hungary%' ORDER BY created"
):
    print(r)

print("\n=== failed runs today by deployment ===")
for r in c.execute(
    """
    SELECT d.name, fr.name, fr.start_time, fr.end_time, frs.message
    FROM flow_run fr
    JOIN deployment d ON d.id = fr.deployment_id
    JOIN flow_run_state frs ON frs.flow_run_id = fr.id
    WHERE frs.type = 'FAILED'
      AND fr.start_time >= '2026-08-26'
      AND d.name IN ('poland-weekday-poll', 'hungary-weekday-poll')
    ORDER BY fr.start_time
    """
):
    print(r)

c.close()
