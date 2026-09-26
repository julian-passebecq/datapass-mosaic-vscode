# Supplier catalog API (simulated by Datapass)

Base URL and API key: shown in the Workbench (API Lab). In `ingest.py` they are `API_BASE_URL` and `API_KEY`.
Every request needs `Authorization: Bearer <API_KEY>`.

## GET /v1/products

| Parameter | Default | Notes |
| --- | --- | --- |
| `page` | 1 | 1-based |
| `page_size` | 100 | at most 100 |

Each run returns the whole catalog (a full snapshot). The answer's `X-Api-Version` header says which version
answered.

v1:

```json
{"data": [{"sku": "SKU-0001", "name": "…", "category": "audio", "price": 49.9}], "page": 1, "page_size": 100, "total_pages": 2, "total": 120}
```

## Changelog

- **v2** (rolling out): `price` is renamed `unit_price`; new field `currency` (ISO 4217). New products are added and
  some are repriced. The `Deprecation` header explains the rename.
