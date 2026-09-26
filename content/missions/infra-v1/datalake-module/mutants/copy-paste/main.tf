terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
}

resource "azurerm_resource_group" "sales" {
  name     = "rg-sales-lake-dev"
  location = "westeurope"
  tags     = { cost_center = "CC-4410", env = "dev", team = "sales" }
}

resource "azurerm_storage_account" "sales" {
  name                            = "stsaleslakedev01"
  resource_group_name             = azurerm_resource_group.sales.name
  location                        = azurerm_resource_group.sales.location
  account_tier                    = "Standard"
  account_replication_type        = "ZRS"
  is_hns_enabled                  = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = azurerm_resource_group.sales.tags
}

resource "azurerm_storage_container" "sales_zone" {
  for_each           = toset(["bronze", "silver", "gold"])
  name               = each.key
  storage_account_id = azurerm_storage_account.sales.id
}

resource "azurerm_resource_group" "marketing" {
  name     = "rg-marketing-lake-dev"
  location = "westeurope"
  tags     = { cost_center = "CC-4410", env = "dev", team = "marketing" }
}

resource "azurerm_storage_account" "marketing" {
  name                            = "stmarketinglakedev01"
  resource_group_name             = azurerm_resource_group.marketing.name
  location                        = azurerm_resource_group.marketing.location
  account_tier                    = "Standard"
  account_replication_type        = "ZRS"
  is_hns_enabled                  = true
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = azurerm_resource_group.marketing.tags
}

resource "azurerm_storage_container" "marketing_zone" {
  for_each           = toset(["bronze", "silver", "gold"])
  name               = each.key
  storage_account_id = azurerm_storage_account.marketing.id
}
