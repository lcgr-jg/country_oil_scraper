# Warehouse data

- `oil_demand.duckdb` (this folder’s live file) is **gitignored**. Rebuild with:

  ```powershell
  python scripts/consolidate_warehouse.py
  ```

- **Dated backups** under `backups/` are committed on purpose as point-in-time snapshots
  (e.g. `oil_demand_YYYY-MM-DD.duckdb`). Add a new dated copy when you want a
  GitHub-visible backup; do not commit every local rebuild.
