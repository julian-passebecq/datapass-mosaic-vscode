"""Factory Lab: a bounded, deterministic Data Factory pipeline simulator.

Pipeline JSON in the Microsoft Fabric Data Factory, Azure Data Factory or Azure
Synapse format is validated and simulated locally. Nothing connects to Fabric,
Azure or Databricks. Selected activities (Copy, Lookup, Script, stored
procedures, notebooks) can run against the local catalog through an adapter;
everything else follows a scenario.
"""
