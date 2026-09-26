# Work in progress (Tom, before his holiday). Not applied anywhere yet.

resource "azurerm_resource_group" "this" {
    name = "rg-${var.team}-lake-${var.env}"
  location = var.location
  tags = var.tags
}

resource "azurerm_storage_account" "this" {
  name = "stsaleslakedev01" # TODO: one per team
  resource_group_name = azurerm_resource_group.this.name
  location   = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "ZRS"
  is_hns_enabled = true
  min_tls_version = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags = var.tags
}

# TODO: one container per zone, and the outputs the root module needs.
