output "sales_dfs_endpoint" {
  description = "The sales lake's ADLS Gen2 endpoint."
  value       = module.sales.dfs_endpoint
}

output "marketing_dfs_endpoint" {
  description = "The marketing lake's ADLS Gen2 endpoint."
  value       = module.marketing.dfs_endpoint
}
