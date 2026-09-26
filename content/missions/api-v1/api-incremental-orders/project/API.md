# Order service API (simulated by Datapass)

Base URL and API key: shown in the Workbench (API Lab). In `ingest.py` they are `API_BASE_URL` and `API_KEY`.
Every request needs `Authorization: Bearer <API_KEY>`.

## GET /v1/orders

| Parameter | Default | Notes |
| --- | --- | --- |
| `updated_since` | none | ISO 8601 timestamp, e.g. `2026-09-20T00:00:00Z`; only orders with `updated_at >= updated_since` (inclusive) |
| `page` | 1 | 1-based |
| `page_size` | 100 | at most 100 |

Orders come sorted by `updated_at`, then `order_id`.

```json
{
  "data": [{"order_id": 70001, "customer_id": 1042, "status": "paid", "amount": 120.5, "updated_at": "2026-09-01T08:00:00Z"}],
  "page": 1, "page_size": 100, "total_pages": 3, "total": 300
}
```

An order that changes (status `delivered` or `cancelled`) comes back with a later `updated_at`.

The vendor bills per record returned.
