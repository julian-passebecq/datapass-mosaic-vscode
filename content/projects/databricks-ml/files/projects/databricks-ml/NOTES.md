# Wind farm lakehouse review

Write your answers in a few lines. The lab's compute and cost figures are illustrative (lab DBUs):
compare them with each other, not with an Azure invoice.

## Compute and cost

- Which compute (job cluster, all-purpose cluster, serverless, SQL warehouse) does each job use?
- How many lab DBUs does a run of `turbine_features` cost, and how many more when the first attempt fails?

## Unity Catalog

- Which minimal privileges did `sp-feature-eng` get, and why not `ALL PRIVILEGES` on the catalog?
- Who owns `main.silver.turbine_features` and `main.ml.power_model`?

## MLflow

- Which model version holds the `champion` alias, and why does the scoring not need a code change?
