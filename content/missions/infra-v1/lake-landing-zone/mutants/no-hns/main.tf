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

locals {
  tags = {
    owner       = "priya.nair"
    cost_center = "CC-4410"
    env         = "dev"
  }
}

import {
  to = azurerm_resource_group.lake
  id = "/subscriptions/6d1f2c3a-0b4e-4c8d-9a7f-2e5b8c1d4f60/resourceGroups/rg-saleslake-dev"
}

resource "azurerm_resource_group" "lake" {
  name     = "rg-saleslake-dev"
  location = "westeurope"
  tags     = local.tags
}

resource "azurerm_storage_account" "lake" {
  name                            = "stsaleslakedev01"
  resource_group_name             = azurerm_resource_group.lake.name
  location                        = azurerm_resource_group.lake.location
  account_tier                    = "Standard"
  account_replication_type        = "ZRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false
  tags                            = local.tags
}

resource "azurerm_storage_container" "zone" {
  for_each           = var.zones
  name               = each.key
  storage_account_id = azurerm_storage_account.lake.id
}
