# Microsoft Fabric capacities

Reference sheet for the concept checks (pack `concepts-v1`). Datapass does not connect to Fabric: the Cloud Lab
simulates Fabric-like work on your computer. Checked against Microsoft Learn on 2026-09-26; prices and limits change,
so confirm on Microsoft's pages before you buy.

## SKUs and capacity units

| SKU | Capacity units (CU) | Power BI viewing |
|---|---|---|
| F2 … F32 | 2 … 32 | viewers need Power BI Pro or PPU |
| F64 | 64 | free-licence users can view content (Premium P1 equivalent) |
| F128 … F2048 | 128 … 2048 | as F64 |

- The number in the SKU **is** its capacity units: F64 = 64 CUs.
- One capacity serves many workspaces; every workload (Spark, pipelines, warehouse, Power BI) draws from the same CUs.
- A Fabric trial gives an F64-sized capacity for a limited time.

## Billing

- **Pay-as-you-go** is billed per second while the capacity runs and can be **paused**: pausing stops the compute
  charge. **OneLake storage is billed separately** and continues while paused.
- **Reservations** lower the price for a one-year commitment; a reserved capacity is not paused to save money.

## Smoothing, bursting and throttling

- **Bursting**: an operation may use more CUs than the SKU for a short time.
- **Smoothing** spreads that usage forward: **interactive** operations (a report query) over at least 5 minutes,
  **background** operations (Spark jobs, pipelines, refreshes) over **24 hours**.
- **Throttling** starts when the smoothed future usage (carry-forward) grows too large:

| Future usage already consumed | What happens |
|---|---|
| up to 10 minutes | nothing (overage protection) |
| 10 to 60 minutes | new **interactive** operations are **delayed** (20 seconds) |
| 60 minutes to 24 hours | **interactive** operations are **rejected** |
| over 24 hours | **background** operations are **rejected** too |

- The Fabric Capacity Metrics app shows usage, smoothing and throttling per operation.
