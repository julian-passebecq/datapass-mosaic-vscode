import time

import httpx


def get(client, params, attempts=4):
    for attempt in range(attempts):
        response = client.get("/v1/orders", params=params)
        if response.status_code < 500:
            response.raise_for_status()
            return response.json()
        time.sleep(0.2 * 2 ** attempt)
    response.raise_for_status()


orders = []
with httpx.Client(base_url=API_BASE_URL, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10) as client:
    cursor = None
    while True:
        params = {"limit": 100, **({"cursor": cursor} if cursor else {})}
        body = get(client, params)
        orders.extend(body["data"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

bronze.merge("api_orders", orders, key="order_id")
print(f"loaded {len(orders)} orders")
