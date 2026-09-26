import httpx


def normalize(product):
    # v2 renamed price to unit_price: downstream still reads price.
    if "unit_price" in product:
        product = {**product, "price": product["unit_price"]}
        del product["unit_price"]
    return product


products = []
with httpx.Client(base_url=API_BASE_URL, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10) as client:
    page, total_pages = 1, 1
    while page <= total_pages:
        response = client.get("/v1/products", params={"page": page, "page_size": 100})
        response.raise_for_status()
        body = response.json()
        products.extend(body["data"])
        total_pages = body["total_pages"]
        page += 1

# currency is new in v2: add it on purpose.
bronze.merge("api_products", products, key="sku", evolve=True)
print(f"loaded {len(products)} products (API v{response.headers.get('X-Api-Version')})")
