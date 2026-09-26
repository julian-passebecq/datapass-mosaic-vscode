# Orders API (simulated by Datapass)

Base URL and API key: shown in the Workbench (API Lab). In `ingest.py` they are `API_BASE_URL` and `API_KEY`.
Every request needs `Authorization: Bearer <API_KEY>`.

## GET /v1/orders

| Parameter | Default | Notes |
| --- | --- | --- |
| `limit` | 100 | at most 100 |
| `cursor` | none | the `next_cursor` of the previous answer; omit it for the first page |

```json
{
  "data": [{"order_id": 50001, "customer_id": 1042, "status": "paid", "amount": 120.5, "created_at": "2026-09-01T08:00:00Z"}],
  "next_cursor": "bzoxMDA"
}
```

`next_cursor` is `null` on the last page. Cursors are opaque: don't build them yourself.

## Errors

- `401`: no or wrong API key.
- `400`: a bad parameter or cursor.
- `502` / `503`: the gateway failed; the same request usually works a moment later.
