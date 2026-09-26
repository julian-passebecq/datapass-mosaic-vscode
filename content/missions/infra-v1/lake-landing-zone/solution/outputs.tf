output "dfs_endpoint" {
  description = "The ADLS Gen2 endpoint the pipelines use."
  value       = azurerm_storage_account.lake.primary_dfs_endpoint
}
