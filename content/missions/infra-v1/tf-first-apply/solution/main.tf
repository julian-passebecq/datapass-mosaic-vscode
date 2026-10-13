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
    env   = var.env
    owner = "iot-team"
  }
}

resource "azurerm_resource_group" "main" {
  name     = "rg-sensors-${var.env}"
  location = var.location
  tags     = local.tags
}

resource "azurerm_storage_account" "raw" {
  name                     = "stsensorsraw${var.env}01"
  resource_group_name      = azurerm_resource_group.main.name
  location                 = azurerm_resource_group.main.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  min_tls_version          = "TLS1_2"
  tags                     = local.tags
}
