"""Load the clickstream events into bronze.api_events. See API.md and TICKET.md.

In scope: API_BASE_URL, API_KEY and bronze (append, merge, overwrite, query, columns). Run it from the Workbench.
"""
import time

import httpx

headers = {"Authorization": f"Bearer {API_KEY}"}
events = []
page, total_pages = 1, 1
while page <= total_pages:
    response = httpx.get(f"{API_BASE_URL}/v1/events", headers=headers, params={"page": page})
    if response.status_code == 429:
        time.sleep(0.2)  # TODO: the vendor says this is not how to handle a 429
        continue
    response.raise_for_status()
    body = response.json()
    events.extend(body["data"])
    total_pages = body["total_pages"]
    page += 1

bronze.overwrite("api_events", events)
print(f"loaded {len(events)} events")
