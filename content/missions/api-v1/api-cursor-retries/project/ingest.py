"""Load every order into bronze.api_orders. See API.md and TICKET.md.

In scope: API_BASE_URL, API_KEY and bronze (append, merge, overwrite, query, columns). Run it from the Workbench.
"""
import httpx

headers = {"Authorization": f"Bearer {API_KEY}"}
orders = []
cursor = None
while True:
    params = {"limit": 100}
    if cursor:
        params["cursor"] = cursor
    response = httpx.get(f"{API_BASE_URL}/v1/orders", headers=headers, params=params)
    response.raise_for_status()  # TODO: the gateway sometimes answers 503 or 502
    body = response.json()
    orders.extend(body["data"])
    cursor = body["next_cursor"]
    if not cursor:
        break

bronze.overwrite("api_orders", orders)
print(f"loaded {len(orders)} orders")
