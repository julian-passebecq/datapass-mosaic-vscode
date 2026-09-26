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
    cost_center = "CC-4410"
    env         = "dev"
  }
}

module "sales" {
  source = "Azure/avm-res-storage-storageaccount/azurerm"
  team   = "sales"
  tags   = local.tags
}

module "marketing" {
  source = "Azure/avm-res-storage-storageaccount/azurerm"
  team   = "marketing"
  tags   = local.tags
}
