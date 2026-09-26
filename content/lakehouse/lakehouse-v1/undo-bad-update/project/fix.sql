-- customers is a DuckLake table (the lake is attached as `lake`). Look at its history before you change anything:
SELECT snapshot_id, changes FROM lake.snapshots() ORDER BY snapshot_id;
