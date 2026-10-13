# REST APIs for ingestion

Cheatsheet for the Learning path *Orchestration in production* and the API Lab. The API Lab's API is simulated
(127.0.0.1, seeded data and faults); your `ingest.py` runs for real as trusted local Python and writes real DuckDB
tables in bronze.

## Status codes

| Code | Meaning | Retry? |
|---|---|---|
| 200, 201, 204 | success | - |
| 400 | the request is wrong | no: fix it |
| 401 / 403 | not authenticated / not allowed | no: fix credentials or scope |
| 404 | not found | usually no |
| 409 | conflict | depends on the API |
| 429 | rate limited | yes, after `Retry-After` |
| 500 | server error | sometimes, a few times |
| 502, 503, 504 | gateway or service temporarily unavailable | yes, with backoff |

## Retries

- Exponential backoff with a cap and jitter: `sleep(random.uniform(0, min(cap, base * 2 ** attempt)))`.
- `Retry-After` (seconds or an HTTP date) wins over your own delay.
- Bound attempts and total time; after the last attempt, fail loudly.
- Idempotent methods (RFC 9110): GET, HEAD, PUT, DELETE, OPTIONS. POST is not; use an idempotency key if offered.

## Pagination

| Style | Risk |
|---|---|
| Offset / page number | inserts or deletes shift pages: rows skipped or repeated |
| Cursor / keyset (`next` token, `after=<last id>`) | stable; follow it until it is absent |

An empty page is not always the end: stop when the API says there is no next page.

## Incremental loads

1. Read the stored watermark (`updated_since`).
2. Fetch every page above it.
3. Write the batch idempotently (MERGE on the business key; duplicates are normal with at-least-once delivery).
4. Only then store the new watermark (the highest `updated_at` written).

Schema drift: new fields arrive without notice. Decide explicitly: evolve the table, or reject and alert.
Never log tokens or full headers.
