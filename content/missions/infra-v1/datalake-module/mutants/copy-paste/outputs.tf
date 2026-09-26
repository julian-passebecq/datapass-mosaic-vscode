output "sales_dfs_endpoint" {
  value = azurerm_storage_account.sales.primary_dfs_endpoint
}

output "marketing_dfs_endpoint" {
  value = azurerm_storage_account.marketing.primary_dfs_endpoint
}
