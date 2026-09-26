locals {
  tags = merge(var.tags, { team = var.team })
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${var.team}-lake-${var.env}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_storage_account" "this" {
  name                            = "st${var.team}lake${var.env}01"
  resource_group_name             = azurerm_resource_group.this.name
  location                        = azurerm_resource_group.this.location
  account_tier                    = "Standard"
  account_replication_type        = "ZRS"
  is_hns_enabled                  = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = local.tags
}

resource "azurerm_storage_container" "zone" {
  count              = length(var.zones)
  name               = tolist(var.zones)[count.index]
  storage_account_id = azurerm_storage_account.this.id
}
