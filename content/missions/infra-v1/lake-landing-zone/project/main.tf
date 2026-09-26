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

# Priya created this resource group by hand in the portal last week.
resource "azurerm_resource_group" "lake" {
  name     = "rg-saleslake-dev"
  location = "westeurope"
}

resource "azurerm_storage_account" "lake" {
  name                     = "stsaleslakedev01"
  resource_group_name      = azurerm_resource_group.lake.name
  location                 = azurerm_resource_group.lake.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
}
