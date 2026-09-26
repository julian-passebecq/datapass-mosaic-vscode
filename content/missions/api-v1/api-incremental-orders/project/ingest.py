"""Nightly orders load into bronze.api_orders_inc. See API.md and TICKET.md.

In scope: API_BASE_URL, API_KEY and bronze (append, merge, overwrite, query, columns). Run it from the Workbench.
"""
import httpx

headers = {"Authorization": f"Bearer {API_KEY}"}
params = {"page": 1, "page_size": 100}
# TODO: incremental: ask only for what changed since the last load (the watermark)

orders = []
total_pages = 1
while params["page"] <= total_pages:
    response = httpx.get(f"{API_BASE_URL}/v1/orders", headers=headers, params=params)
    response.raise_for_status()
    body = response.json()
    orders.extend(body["data"])
    total_pages = body["total_pages"]
    params["page"] += 1

bronze.overwrite("api_orders_inc", orders)
print(f"loaded {len(orders)} orders")
