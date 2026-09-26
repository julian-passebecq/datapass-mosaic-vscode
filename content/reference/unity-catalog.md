# Unity Catalog

Reference sheet for the concept checks (pack `concepts-v1`). The Cloud Lab's Databricks tab checks a Unity Catalog
privilege subset on the local catalog; it is not Databricks. Checked against the Databricks documentation on 2026-09-26.

## Names

- A **metastore** (one per region) holds **catalogs** → **schemas** → tables, views, volumes, functions and models.
- Objects are named **`catalog.schema.object`**, for example `main.sales.orders`.

## Privileges

- Reading `main.sales.orders` needs **`USE CATALOG`** on `main`, **`USE SCHEMA`** on `main.sales` and **`SELECT`** on the
  table. Privileges granted on a catalog or schema are **inherited** by the objects below it.
- Other common privileges: `MODIFY` (write rows), `CREATE TABLE`, `READ VOLUME` / `WRITE VOLUME`, `EXECUTE` (functions).
- Every object has an **owner**, who can grant privileges on it.

## Managed and external

| | Managed table | External table |
|---|---|---|
| Files | in storage Unity Catalog manages | at a path you give, under an **external location** |
| `DROP TABLE` | Unity Catalog deletes the files (after a retention period during which `UNDROP` works) | only the metadata goes; files stay |

- **Storage credentials** hold the cloud identity; **external locations** pair a credential with a storage path.
- **Volumes** govern non-tabular files (CSV drops, images, wheels) with the same three-level names and grants.
