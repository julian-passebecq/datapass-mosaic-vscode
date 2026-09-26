variable "zones" {
  description = "The medallion zones of the lake, one container each."
  type        = set(string)
  default     = ["bronze", "silver", "gold"]
}
