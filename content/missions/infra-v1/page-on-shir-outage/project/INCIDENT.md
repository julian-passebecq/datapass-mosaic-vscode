# Incident 2026-10-05: nightly loads late, nobody paged

Timeline as the business saw it (times in UTC):

- 01:00 the nightly backup of vm-shir-01 runs, as every night (a few minutes of high CPU, harmless).
- around 02:10 the copy activities of `pl_ingest_orders` stop picking up work: they wait in the queue of the
  self-hosted integration runtime `shir-onprem`, which runs on vm-shir-01.
- 07:30 the sales team calls: yesterday's orders are missing from the reports.
- 07:45 the on-call restarts the Integration Runtime service; the queue drains by 08:10.

No alert fired. The action group `ag-data-oncall` (the on-call phone and the team channel) exists in
`rg-integration-prod`; nothing points at it yet.

Useful commands:

- `az resource list -g rg-integration-prod -o table`
- `az monitor metrics list-definitions --resource adf-sales-prod`
- `az monitor metrics list --resource vm-shir-01 --metric "Percentage CPU" --interval 5m --start-time 2026-10-05T00:30:00Z --end-time 2026-10-05T03:30:00Z`
