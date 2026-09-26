# CRM API (simulated by Datapass)

Base URL and API key: shown in the Workbench (API Lab). In `ingest.py` they are `API_BASE_URL` and `API_KEY`.

Every request needs `Authorization: Bearer <API_KEY>`; without it the API answers `401`.

## GET /v1/customers

| Parameter | Default | Notes |
| --- | --- | --- |
| `page` | 1 | 1-based |
| `page_size` | 50 | at most 100 |

```json
{
  "data": [{"id": 1001, "name": "…", "email": "…", "country": "FR", "created_at": "2025-03-02T08:00:00Z"}],
  "page": 1,
  "page_size": 50,
  "total_pages": 5,
  "total": 230
}
```

A page past the end returns `"data": []`.
