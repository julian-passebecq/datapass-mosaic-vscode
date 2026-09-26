"""The simulated `hashicorp/azurerm` provider: a documented subset of its resource types and arguments.

The names, arguments, defaults and "forces replacement" flags follow the real azurerm provider (4.x) for the subset
listed here; everything else is refused as an unsupported resource type or argument. Resources are created, updated
and deleted in the simulated subscription of `world.json`, never in Azure. Durations are teaching figures.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Callable

PROVIDER_SOURCE = 'hashicorp/azurerm'
PROVIDER_ADDRESS = 'provider["registry.terraform.io/hashicorp/azurerm"]'
PROVIDER_VERSION = '4.14.0'

LOCATIONS = {
    'westeurope', 'northeurope', 'francecentral', 'germanywestcentral', 'swedencentral', 'uksouth', 'eastus',
    'eastus2', 'westus2', 'centralus',
}
LOCATION_ALIASES = {'West Europe': 'westeurope', 'North Europe': 'northeurope', 'France Central': 'francecentral',
                    'Germany West Central': 'germanywestcentral', 'Sweden Central': 'swedencentral',
                    'UK South': 'uksouth', 'East US': 'eastus', 'East US 2': 'eastus2', 'West US 2': 'westus2',
                    'Central US': 'centralus'}


@dataclass
class Arg:
    type: str                      # string, number, bool, list(string), map(string)
    required: bool = False
    force_new: bool = False
    default: Any = None
    choices: tuple[str, ...] = ()
    pattern: str | None = None
    message: str | None = None
    # Not settable: computed by the provider.
    computed_only: bool = False
    deprecated: str | None = None


@dataclass
class BlockSpec:
    args: dict[str, Arg]
    required: bool = False
    max_items: int = 1
    force_new: bool = False


@dataclass
class ResourceType:
    name: str
    args: dict[str, Arg]
    id: Callable[[dict, dict], str]
    # The id of the parent the resource needs (resource group, storage account, virtual network), or None.
    parent: Callable[[dict, dict], tuple[str, str] | None]
    computed: Callable[[dict, dict], dict] = lambda attrs, azure: {}
    blocks: dict[str, BlockSpec] = field(default_factory=dict)
    seconds: int = 5
    # Names that must be unique across Azure (a key in world.azure.taken_names).
    global_name: str | None = None
    exactly_one_of: tuple[str, ...] = ()
    arm_type: str = ''


def rg_id(azure: dict, name: str) -> str:
    return f'/subscriptions/{azure["subscription_id"]}/resourceGroups/{name}'


def _in_rg(provider: str, kind: str) -> Callable[[dict, dict], str]:
    return lambda a, azure: f'{rg_id(azure, a["resource_group_name"])}/providers/{provider}/{kind}/{a["name"]}'


def _rg_parent(a: dict, azure: dict) -> tuple[str, str]:
    return rg_id(azure, a['resource_group_name']), f'Resource group {a["resource_group_name"]!r} could not be found.'


TAGS = Arg('map(string)', default={})
NAME_RG = {
    'resource_group_name': Arg('string', required=True, force_new=True),
    'location': Arg('string', required=True, force_new=True),
}


def _storage_computed(a: dict, azure: dict) -> dict:
    name = a['name']
    out = {'primary_blob_endpoint': f'https://{name}.blob.core.windows.net/',
           'primary_dfs_endpoint': f'https://{name}.dfs.core.windows.net/',
           'primary_web_endpoint': f'https://{name}.z6.web.core.windows.net/',
           'primary_location': a['location']}
    return out


def _container_id(a: dict, azure: dict) -> str:
    return f'{a["storage_account_id"]}/blobServices/default/containers/{a["name"]}'


def _container_parent(a: dict, azure: dict) -> tuple[str, str]:
    account = a['storage_account_id']
    return account, f'Storage account {account.rsplit("/", 1)[-1]!r} could not be found.'


def _subnet_id(a: dict, azure: dict) -> str:
    return (f'{rg_id(azure, a["resource_group_name"])}/providers/Microsoft.Network/virtualNetworks/'
            f'{a["virtual_network_name"]}/subnets/{a["name"]}')


def _subnet_parent(a: dict, azure: dict) -> tuple[str, str]:
    vnet = f'{rg_id(azure, a["resource_group_name"])}/providers/Microsoft.Network/virtualNetworks/{a["virtual_network_name"]}'
    return vnet, f'Virtual network {a["virtual_network_name"]!r} could not be found.'


RESOURCES: dict[str, ResourceType] = {
    'azurerm_resource_group': ResourceType(
        'azurerm_resource_group',
        {'name': Arg('string', required=True, force_new=True, pattern=r'^[-\w\._\(\)]{1,90}$',
                     message='resource group names are 1 to 90 letters, digits, dashes, underscores, dots and parentheses'),
         'location': Arg('string', required=True, force_new=True),
         'managed_by': Arg('string', force_new=True),
         'tags': TAGS},
        id=lambda a, azure: rg_id(azure, a['name']), parent=lambda a, azure: None, seconds=2,
        arm_type='Microsoft.Resources/resourceGroups'),
    'azurerm_storage_account': ResourceType(
        'azurerm_storage_account',
        {'name': Arg('string', required=True, force_new=True, pattern=r'^[a-z0-9]{3,24}$',
                     message='name can only consist of lowercase letters and numbers, and must be between 3 and 24 '
                             'characters long'),
         **NAME_RG,
         'account_tier': Arg('string', required=True, force_new=True, choices=('Standard', 'Premium')),
         'account_replication_type': Arg('string', required=True,
                                         choices=('LRS', 'GRS', 'RAGRS', 'ZRS', 'GZRS', 'RAGZRS')),
         'account_kind': Arg('string', default='StorageV2',
                             choices=('BlobStorage', 'BlockBlobStorage', 'FileStorage', 'Storage', 'StorageV2')),
         'access_tier': Arg('string', default='Hot', choices=('Hot', 'Cool', 'Cold', 'Premium')),
         'is_hns_enabled': Arg('bool', force_new=True, default=False),
         'min_tls_version': Arg('string', default='TLS1_2', choices=('TLS1_0', 'TLS1_1', 'TLS1_2')),
         'https_traffic_only_enabled': Arg('bool', default=True),
         'public_network_access_enabled': Arg('bool', default=True),
         'allow_nested_items_to_be_public': Arg('bool', default=True),
         'shared_access_key_enabled': Arg('bool', default=True),
         'tags': TAGS},
        id=_in_rg('Microsoft.Storage', 'storageAccounts'), parent=_rg_parent, computed=_storage_computed,
        seconds=24, global_name='storage_account', arm_type='Microsoft.Storage/storageAccounts'),
    'azurerm_storage_container': ResourceType(
        'azurerm_storage_container',
        {'name': Arg('string', required=True, force_new=True, pattern=r'^(?!.*--)[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$',
                     message='container names are 3 to 63 lowercase letters, digits and single dashes, starting and '
                             'ending with a letter or digit'),
         'storage_account_id': Arg('string', force_new=True),
         'storage_account_name': Arg('string', force_new=True,
                                     deprecated='storage_account_name is deprecated in azurerm 4.x: use storage_account_id'),
         'container_access_type': Arg('string', default='private', choices=('private', 'blob', 'container')),
         'metadata': Arg('map(string)', default={})},
        id=_container_id, parent=_container_parent, seconds=1, exactly_one_of=('storage_account_id',),
        arm_type='Microsoft.Storage/storageAccounts/blobServices/containers'),
    'azurerm_virtual_network': ResourceType(
        'azurerm_virtual_network',
        {'name': Arg('string', required=True, force_new=True), **NAME_RG,
         'address_space': Arg('list(string)', required=True), 'tags': TAGS},
        id=_in_rg('Microsoft.Network', 'virtualNetworks'), parent=_rg_parent, seconds=6,
        arm_type='Microsoft.Network/virtualNetworks'),
    'azurerm_subnet': ResourceType(
        'azurerm_subnet',
        {'name': Arg('string', required=True, force_new=True),
         'resource_group_name': Arg('string', required=True, force_new=True),
         'virtual_network_name': Arg('string', required=True, force_new=True),
         'address_prefixes': Arg('list(string)', required=True)},
        id=_subnet_id, parent=_subnet_parent, seconds=5, arm_type='Microsoft.Network/virtualNetworks/subnets'),
    'azurerm_key_vault': ResourceType(
        'azurerm_key_vault',
        {'name': Arg('string', required=True, force_new=True, pattern=r'^[a-zA-Z][a-zA-Z0-9-]{1,22}[a-zA-Z0-9]$',
                     message='key vault names are 3 to 24 letters, digits and dashes, starting with a letter'),
         **NAME_RG,
         'tenant_id': Arg('string', required=True),
         'sku_name': Arg('string', required=True, choices=('standard', 'premium')),
         'soft_delete_retention_days': Arg('number', default=90),
         'purge_protection_enabled': Arg('bool', default=False),
         'rbac_authorization_enabled': Arg('bool', default=False),
         'tags': TAGS},
        id=_in_rg('Microsoft.KeyVault', 'vaults'), parent=_rg_parent,
        computed=lambda a, azure: {'vault_uri': f'https://{a["name"]}.vault.azure.net/'},
        seconds=80, global_name='key_vault', arm_type='Microsoft.KeyVault/vaults'),
    'azurerm_data_factory': ResourceType(
        'azurerm_data_factory',
        {'name': Arg('string', required=True, force_new=True), **NAME_RG,
         'public_network_enabled': Arg('bool', default=True),
         'managed_virtual_network_enabled': Arg('bool', default=False),
         'tags': TAGS},
        id=_in_rg('Microsoft.DataFactory', 'factories'), parent=_rg_parent,
        blocks={'identity': BlockSpec({'type': Arg('string', required=True,
                                                   choices=('SystemAssigned', 'UserAssigned', 'SystemAssigned, UserAssigned')),
                                       'identity_ids': Arg('list(string)', default=[])})},
        seconds=14, arm_type='Microsoft.DataFactory/factories'),
}

DATA_SOURCES = {'azurerm_client_config', 'azurerm_resource_group', 'azurerm_storage_account'}


def data_source(kind: str, args: dict, azure: dict) -> dict:
    """Read a data source from the simulated subscription."""
    if kind == 'azurerm_client_config':
        return {'id': f'clientConfigs/tenantId={azure["tenant_id"]}', 'tenant_id': azure['tenant_id'],
                'subscription_id': azure['subscription_id'], 'object_id': azure['client_object_id'],
                'client_id': '04b07795-8ddb-461a-bbee-02f9e1bf7b46'}
    if kind == 'azurerm_resource_group':
        name = args.get('name')
        resource = azure['resources'].get(rg_id(azure, str(name)))
        if resource is None:
            raise LookupError(f'Resource group {name!r} was not found.')
        return dict(resource['attributes'])
    if kind == 'azurerm_storage_account':
        rid = f'{rg_id(azure, str(args.get("resource_group_name")))}/providers/Microsoft.Storage/storageAccounts/{args.get("name")}'
        resource = azure['resources'].get(rid)
        if resource is None:
            raise LookupError(f'Storage account {args.get("name")!r} was not found in {args.get("resource_group_name")!r}.')
        return dict(resource['attributes'])
    raise LookupError(f'Unsupported data source {kind}.')


def normalize_location(value: Any) -> Any:
    if isinstance(value, str):
        mapped = LOCATION_ALIASES.get(value, value.replace(' ', '').lower())
        return mapped
    return value


def check_value(rtype: ResourceType, name: str, arg: Arg, value: Any) -> str | None:
    """A validation error message for a known value, as azurerm reports at plan time, or None."""
    if value is None:
        return None
    if arg.choices and value not in arg.choices:
        return f'expected {name} to be one of {list(arg.choices)}, got {value}'
    if arg.pattern and isinstance(value, str) and not re.match(arg.pattern, value):
        return f'{name} {value!r} is invalid: {arg.message or "it does not match " + arg.pattern}'
    if name == 'location' and isinstance(value, str) and normalize_location(value) not in LOCATIONS:
        return f'{value!r} is not a location this lab simulates ({", ".join(sorted(LOCATIONS))})'
    return None


def supported_types() -> str:
    return ', '.join(sorted(RESOURCES))
