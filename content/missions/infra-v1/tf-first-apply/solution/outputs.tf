output "resource_group_id" {
  description = "The id the network team needs for its role assignment."
  value       = azurerm_resource_group.main.id
}
