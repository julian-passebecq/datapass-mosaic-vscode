import httpx

headers = {"Authorization": f"Bearer {API_KEY}"}
customers = []
with httpx.Client(base_url=API_BASE_URL, headers=headers, timeout=10) as client:
    page, total_pages = 1, 1
    while page <= total_pages:
        response = client.get("/v1/customers", params={"page": page, "page_size": 100})
        response.raise_for_status()
        body = response.json()
        customers.extend(body["data"])
        total_pages = body["total_pages"]
        page += 1

bronze.append("api_customers", customers)
print(f"loaded {len(customers)} customers")
