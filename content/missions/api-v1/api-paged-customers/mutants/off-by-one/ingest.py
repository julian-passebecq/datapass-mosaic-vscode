import httpx

headers = {"Authorization": f"Bearer {API_KEY}"}
with httpx.Client(base_url=API_BASE_URL, headers=headers, timeout=10) as client:
    first = client.get("/v1/customers", params={"page": 1, "page_size": 100})
    first.raise_for_status()
    body = first.json()
    customers = list(body["data"])
    for page in range(2, body["total_pages"]):
        response = client.get("/v1/customers", params={"page": page, "page_size": 100})
        response.raise_for_status()
        customers.extend(response.json()["data"])

bronze.overwrite("api_customers", customers)
print(f"loaded {len(customers)} customers")
