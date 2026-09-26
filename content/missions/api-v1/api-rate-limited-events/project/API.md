# Events API (simulated by Datapass)

Base URL and API key: shown in the Workbench (API Lab). In `ingest.py` they are `API_BASE_URL` and `API_KEY`.
Every request needs `Authorization: Bearer <API_KEY>`.

## GET /v1/events

| Parameter | Default | Notes |
| --- | --- | --- |
| `page` | 1 | 1-based |
| `page_size` | 50 | at most 50 |

```json
{
  "data": [{"event_id": "evt_00042", "type": "checkout", "user_id": 1107, "occurred_at": "2026-09-01T09:08:00Z"}],
  "page": 1, "page_size": 50, "total_pages": 8, "total": 375
}
```

Delivery is **at least once**: an event can appear twice (same `event_id`, same content), on different pages.

## Rate limit

After a few requests the API answers `429 Too Many Requests` with a `Retry-After` header (seconds). Any request
sent before that delay is over gets another 429 and is recorded as a violation of the vendor's terms.
