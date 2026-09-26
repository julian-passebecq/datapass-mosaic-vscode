import httpx

orders = []
with httpx.Client(base_url=API_BASE_URL, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10) as client:
    cursor = None
    while True:
        params = {"limit": 100, **({"cursor": cursor} if cursor else {})}
        response = client.get("/v1/orders", params=params)
        if response.status_code >= 500:
            print("gateway error, keeping what we have")
            break
        response.raise_for_status()
        body = response.json()
        orders.extend(body["data"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

bronze.merge("api_orders", orders, key="order_id")
print(f"loaded {len(orders)} orders")
