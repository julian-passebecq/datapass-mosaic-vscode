import time

import httpx

events = []
with httpx.Client(base_url=API_BASE_URL, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10) as client:
    page, total_pages = 1, 1
    while page <= total_pages:
        response = client.get("/v1/events", params={"page": page, "page_size": 50})
        if response.status_code == 429:
            time.sleep(float(response.headers.get("Retry-After", "1")))
            continue
        response.raise_for_status()
        body = response.json()
        events.extend(body["data"])
        total_pages = body["total_pages"]
        page += 1

bronze.overwrite("api_events", events)
print(f"loaded {len(events)} deliveries")
