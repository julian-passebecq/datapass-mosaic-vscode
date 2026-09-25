"""SQL pool Lab: a bounded simulation of an Azure Synapse dedicated SQL pool (and Fabric Warehouse differences).

T-SQL scripts are parsed by a bounded reader and translated to DuckDB SQL for a
documented subset; data really lives in the local catalog. Distributions,
partitions, columnstore rowgroups and distributed query plans (data movement)
are modelled for teaching; they are not Synapse telemetry. See README.md.
"""
