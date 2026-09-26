"""Load the CRM customers into bronze.api_customers.

Run it from the Workbench (API Lab > Run ingest.py): Datapass runs this file as real local Python (trusted Python
must be on) against the simulated CRM API. You get:

- API_BASE_URL, API_KEY: the simulated API and its key for this mission;
- bronze: bronze.append(table, rows), bronze.merge(table, rows, key=...), bronze.overwrite(table, rows),
  bronze.query(sql), bronze.columns(table).

httpx is installed with the runtime; requests works too if you install it.
"""
import httpx

headers = {"Authorization": f"Bearer {API_KEY}"}

response = httpx.get(f"{API_BASE_URL}/v1/customers", headers=headers, params={"page": 1})
response.raise_for_status()
customers = response.json()["data"]

bronze.overwrite("api_customers", customers)
print(f"loaded {len(customers)} customers")
