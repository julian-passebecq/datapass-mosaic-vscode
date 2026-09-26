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
  source = "./modules/datalake"
  team   = "sales"
  tags   = local.tags
}

module "marketing" {
  source = "./modules/datalake"
  team   = "marketing"
  tags   = local.tags
}
