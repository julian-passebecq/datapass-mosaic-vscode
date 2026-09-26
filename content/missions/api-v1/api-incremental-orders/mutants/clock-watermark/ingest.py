from datetime import datetime, timezone

import httpx

TABLE = "api_orders_inc"

params = {"page": 1, "page_size": 100}
if "updated_at" in bronze.columns(TABLE):
    # "since the last run": the job runs at midnight, so ask for today's changes
    params["updated_since"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")

orders = []
with httpx.Client(base_url=API_BASE_URL, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10) as client:
    total_pages = 1
    while params["page"] <= total_pages:
        response = client.get("/v1/orders", params=params)
        response.raise_for_status()
        body = response.json()
        orders.extend(body["data"])
        total_pages = body["total_pages"]
        params["page"] += 1

bronze.merge(TABLE, orders, key="order_id")
print(f"since {params.get('updated_since', 'the beginning')}: {len(orders)} orders")
