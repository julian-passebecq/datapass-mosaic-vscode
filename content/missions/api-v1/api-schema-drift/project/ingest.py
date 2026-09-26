"""Supplier catalog into bronze.api_products (a full snapshot each run). See API.md and TICKET.md.

In scope: API_BASE_URL, API_KEY and bronze (append, merge, overwrite, query, columns). Run it from the Workbench.
"""
import httpx

headers = {"Authorization": f"Bearer {API_KEY}"}
products = []
page, total_pages = 1, 1
while page <= total_pages:
    response = httpx.get(f"{API_BASE_URL}/v1/products", headers=headers, params={"page": page})
    response.raise_for_status()
    body = response.json()
    products.extend(body["data"])
    total_pages = body["total_pages"]
    page += 1

bronze.merge("api_products", products, key="sku")
print(f"loaded {len(products)} products (API v{response.headers.get('X-Api-Version')})")
