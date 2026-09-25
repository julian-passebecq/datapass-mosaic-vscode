"""Activity types per product: Microsoft Fabric Data Factory, Azure Data Factory and Azure Synapse pipelines.

The three share the pipeline JSON model and orchestration semantics (Azure Data
Factory is the origin), but differ in activity names and in how data is
reached: Azure Data Factory and Synapse use linked services and datasets
referenced by name, while Fabric uses connections and inline dataset settings.
Using an activity outside the product that has it is a validation error that
names the product's equivalent.
"""
from __future__ import annotations

from dataclasses import dataclass

FLAVORS = ('fabric', 'adf', 'synapse')
FLAVOR_LABELS = {'fabric': 'Microsoft Fabric Data Factory', 'adf': 'Azure Data Factory', 'synapse': 'Azure Synapse pipelines'}


@dataclass(frozen=True)
class ActivityType:
    name: str
    label: str
    category: str  # control | move | transform | general | notify | external
    flavors: tuple[str, ...]
    # 'control' types run inner activities or change pipeline state; others are work activities.
    control: bool = False
    # Simulated duration (seconds) when a scenario does not give one; containers add their inner time.
    default_seconds: float = 0.0
    # Required typeProperties keys (validation).
    required: tuple[str, ...] = ()
    # What to use instead in another product, shown when the type is not available there.
    equivalents: tuple[tuple[str, str], ...] = ()


ALL = FLAVORS
AZURE = ('adf', 'synapse')

TYPES: dict[str, ActivityType] = {t.name: t for t in [
    # Control flow (all three products)
    ActivityType('ForEach', 'ForEach', 'control', ALL, True, 0, ('items', 'activities')),
    ActivityType('IfCondition', 'If Condition', 'control', ALL, True, 0, ('expression',)),
    ActivityType('Switch', 'Switch', 'control', ALL, True, 0, ('on',)),
    ActivityType('Until', 'Until', 'control', ALL, True, 0, ('expression', 'activities')),
    ActivityType('Wait', 'Wait', 'control', ALL, True, 0, ('waitTimeInSeconds',)),
    ActivityType('Fail', 'Fail', 'control', ALL, True, 0, ('message', 'errorCode')),
    ActivityType('SetVariable', 'Set variable', 'control', ALL, True, 0, ('variableName',)),
    ActivityType('AppendVariable', 'Append variable', 'control', ALL, True, 0, ('variableName', 'value')),
    ActivityType('Filter', 'Filter', 'control', ALL, True, 0, ('items', 'condition')),
    ActivityType('ExecutePipeline', 'Execute pipeline', 'control', ALL, True, 0, ('pipeline',),
                 (('fabric', 'InvokePipeline (Invoke pipeline) is the current Fabric activity'),)),
    ActivityType('InvokePipeline', 'Invoke pipeline', 'control', ('fabric',), True, 0, (),
                 (('adf', 'ExecutePipeline'), ('synapse', 'ExecutePipeline'))),
    # Move and transform
    ActivityType('Copy', 'Copy data', 'move', ALL, False, 30, ('source', 'sink')),
    ActivityType('Lookup', 'Lookup', 'general', ALL, False, 5, ('source',)),
    ActivityType('Script', 'Script', 'general', ALL, False, 5, ('scripts',)),
    ActivityType('GetMetadata', 'Get Metadata', 'general', ALL, False, 3),
    ActivityType('Delete', 'Delete', 'general', ALL, False, 3),
    ActivityType('WebActivity', 'Web', 'general', ALL, False, 2, ('url', 'method')),
    ActivityType('SqlServerStoredProcedure', 'Stored procedure', 'transform', ALL, False, 10, ('storedProcedureName',)),
    ActivityType('SqlPoolStoredProcedure', 'SQL pool stored procedure', 'transform', ('synapse',), False, 10,
                 ('storedProcedureName',), (('fabric', 'SqlServerStoredProcedure on a Warehouse connection'),
                                            ('adf', 'SqlServerStoredProcedure'))),
    ActivityType('TridentNotebook', 'Notebook', 'transform', ('fabric',), False, 90, ('notebookId',),
                 (('adf', 'DatabricksNotebook (Azure Databricks) or SynapseNotebook in Synapse'),
                  ('synapse', 'SynapseNotebook'))),
    ActivityType('SynapseNotebook', 'Notebook (Synapse Spark pool)', 'transform', ('synapse',), False, 180, ('notebook',),
                 (('fabric', 'TridentNotebook'), ('adf', 'DatabricksNotebook'))),
    ActivityType('DatabricksNotebook', 'Azure Databricks notebook', 'transform', ALL, False, 240, ('notebookPath',)),
    ActivityType('ExecuteDataFlow', 'Data flow (mapping data flow)', 'transform', AZURE, False, 300, ('dataflow',),
                 (('fabric', 'RefreshDataflow (Dataflow Gen2)'),)),
    ActivityType('RefreshDataflow', 'Dataflow Gen2', 'transform', ('fabric',), False, 120, (),
                 (('adf', 'ExecuteDataFlow (mapping data flow)'), ('synapse', 'ExecuteDataFlow (mapping data flow)'))),
    ActivityType('AzureFunctionActivity', 'Azure Function', 'external', ALL, False, 3, ('functionName',)),
    # Fabric notifications
    ActivityType('Teams', 'Teams', 'notify', ('fabric',), False, 2, (),
                 (('adf', 'WebActivity to a Logic App or webhook'), ('synapse', 'WebActivity to a Logic App or webhook'))),
    ActivityType('Office365Outlook', 'Office 365 Outlook', 'notify', ('fabric',), False, 2, (),
                 (('adf', 'WebActivity to a Logic App'), ('synapse', 'WebActivity to a Logic App'))),
]}

CONTAINER_KEYS = {
    'ForEach': ('activities',),
    'Until': ('activities',),
    'IfCondition': ('ifTrueActivities', 'ifFalseActivities'),
    'Switch': ('defaultActivities',),  # plus cases[].activities
}


def availability_error(type_name: str, flavor: str) -> str | None:
    spec = TYPES.get(type_name)
    if spec is None:
        known = ', '.join(sorted(t for t, s in TYPES.items() if flavor in s.flavors))
        return f"Activity type '{type_name}' is not simulated for {FLAVOR_LABELS[flavor]}. Supported: {known}"
    if flavor in spec.flavors:
        return None
    hint = dict(spec.equivalents).get(flavor)
    where = ', '.join(FLAVOR_LABELS[f] for f in spec.flavors)
    return (f"'{type_name}' ({spec.label}) exists in {where}, not in {FLAVOR_LABELS[flavor]}"
            + (f"; use {hint}" if hint else ""))
