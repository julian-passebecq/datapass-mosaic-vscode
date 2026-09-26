# apilab: API ingestion lab

The learner writes real Python (httpx, or requests if installed) that ingests a **simulated REST API** into the
bronze layer of the local catalog. Label: "Simulated API (Datapass), your ingestion code runs for real".

## Truth

| Piece | Truth |
| --- | --- |
| The API | Simulated by Datapass: a small HTTP server (`server.py`) on 127.0.0.1, on its own port, one per active mission. Deterministic seeded data (`scenario.py`); no real service behind it. |
| The learner's code | Real: `missions/<id>/ingest.py` runs as **trusted local Python** in the kernel worker (`runner.py`), refused while trusted Python is off. It makes real HTTP requests to the simulated API. |
| Bronze | Real DuckDB tables in the `bronze` layer, written through `bronze.append / merge / overwrite` (schema enforcement: an unknown column is refused unless `evolve=True`). |
| Checks | Real read-only SQL on bronze, the server's request log (`requests.jsonl`) and the run history (`runs.json`). |

## Security

- The simulated API has its **own** auth: `Authorization: Bearer <key>`, where the key is a fictitious one made per
  mission start (`sim_<name>_<hex>`) and shown to the learner; wrong or missing key: 401. The Host header must be
  exactly `127.0.0.1:<port>` or `localhost:<port>` (DNS rebinding): else 400. GET only.
- The runtime's launch token (`X-Datapass-Token`) never reaches the server or the learner: the server starts with an
  allowlisted environment (`service.server_env`), and the kernel worker already drops `*TOKEN*` variables. The
  runtime's own routes (`/api/local/apilab/*`) stay behind `auth.py` like every other route.
- The request log never records a header value. The server exits when the runtime closes its stdin.
- Trusted Python stays an explicit choice: the lab adds no other way to run code.

## Scenarios

| Scenario | Endpoint | Teaches |
| --- | --- | --- |
| `customers-pages` | `/v1/customers?page=&page_size=` | page pagination, idempotent reruns |
| `orders-cursor` | `/v1/orders?limit=&cursor=` | cursor pagination; a 503 and a 502 on the first attempt of two pages, per run |
| `events-ratelimit` | `/v1/events?page=` | 429 + `Retry-After` every 4th request (a request during the window is logged as a violation); at-least-once duplicates |
| `orders-incremental` | `/v1/orders?updated_since=&page=` | watermark, inclusive `updated_since`, merge of updated records; day 2 adds 40 orders and updates 25 |
| `products-drift` | `/v1/products?page=` | day 2 (v2): `price` renamed `unit_price`, new `currency`, repriced and new products |

## Missions (`content/missions/api-v1`)

`mission.json` follows missionlab's (ticket, acceptance, requires, hints, reference) with `lab: "apilab"`, an `api`
block (`scenario`, `seed`, the bronze `tables` dropped at start) and `batches` as the API's days. `project/` holds the
starter `ingest.py` and `API.md`; `solution/ingest.py` and `mutants/<name>/ingest.py` stay out of the VSIX.
missionlab skips this pack (`OTHER_PACKS`).

| Check kind | Looks at |
| --- | --- |
| `sql` | missionlab's: a read-only query on bronze, compared to the expected rows. |
| `api_run` | The last run finished without an error (on a given day). |
| `api_log` | The last run's requests to an endpoint: `complete` (the last page was read), `saw_status`, `retried_5xx`, `retry_after_respected`, `param_required`, `max_records`, `authorized`. |

## API

- `POST /api/local/apilab/start {mission_id}`: copy `project/` (never over the learner's files), drop the mission's
  bronze tables, start a fresh server (new key, day 1, empty log).
- `POST /api/local/apilab/advance {mission_id, batch_id}`: the next day of the API.
- `POST /api/local/apilab/run {mission_id}`: run `ingest.py` (kernel op `apilab_run`), record the run.
- `POST /api/local/apilab/check {mission_id}`, `POST /api/local/apilab/state {mission_id?}`, `POST /api/local/apilab/stop`.

`scripts/api_lab_smoke.py` plays every mission (references pass; untouched missions, starters and mutants fail) and
checks the security rules above.
