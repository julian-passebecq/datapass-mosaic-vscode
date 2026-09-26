variable "team" {
  description = "The team that owns the lake. It becomes part of the storage account name."
  type        = string

  validation {
    condition     = length(var.team) >= 2 && length(var.team) <= 10 && lower(var.team) == var.team
    error_message = "team must be 2 to 10 lowercase letters: storage account names allow nothing else."
  }
}

variable "env" {
  description = "dev, test or prod."
  type        = string
  default     = "dev"
}

variable "location" {
  type    = string
  default = "westeurope"
}

variable "tags" {
  description = "Tags every resource of the lake gets (the module adds team)."
  type        = map(string)
  default     = {}
}

variable "zones" {
  description = "The medallion zones of the lake, one container each."
  type        = set(string)
  default     = ["bronze", "silver", "gold"]
}
