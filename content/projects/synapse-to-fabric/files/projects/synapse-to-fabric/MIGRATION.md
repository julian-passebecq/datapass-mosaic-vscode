# Migrating the Synapse dedicated pool to Fabric Warehouse

Complete this checklist for the team. One or two lines per item.

## Physical design

- Which tables were `REPLICATE`, which were `HASH` and on which column? What becomes of that choice in Fabric?
- Which tables were partitioned? What replaces partitions and partition elimination in Fabric?

## Types and constraints

- Which types did you have to change (`nvarchar`, `money`, ...) and to what?
- Primary and foreign keys: what do they guarantee in Synapse, and in Fabric?

## Loading

- Which stored procedure does the pipeline call, with which typed parameters?
- What would change for this pipeline in Fabric Data Factory?

## Governance

- Where does `margin_amount` of `gold.fct_sales` come from (lineage), and which star model check reassures you about its grain?
