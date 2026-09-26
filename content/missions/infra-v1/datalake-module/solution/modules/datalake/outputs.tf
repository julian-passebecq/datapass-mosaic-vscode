output "dfs_endpoint" {
  description = "The account's ADLS Gen2 endpoint."
  value       = azurerm_storage_account.this.primary_dfs_endpoint
}

output "resource_group_name" {
  value = azurerm_resource_group.this.name
}
