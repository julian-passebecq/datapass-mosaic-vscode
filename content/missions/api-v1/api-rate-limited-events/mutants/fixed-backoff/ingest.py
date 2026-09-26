import time

import httpx

events = []
with httpx.Client(base_url=API_BASE_URL, headers={"Authorization": f"Bearer {API_KEY}"}, timeout=10) as client:
    page, total_pages = 1, 1
    while page <= total_pages:
        response = client.get("/v1/events", params={"page": page, "page_size": 50})
        if response.status_code == 429:
            time.sleep(0.3)
            continue
        response.raise_for_status()
        body = response.json()
        events.extend(body["data"])
        total_pages = body["total_pages"]
        page += 1

bronze.merge("api_events", events, key="event_id")
print(f"loaded {len(events)} deliveries")
