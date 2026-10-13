variable "location" {
  description = "Azure region of the sensors platform."
  type        = string
  default     = "westeurope"
}

variable "env" {
  description = "Environment name, part of every resource name."
  type        = string

  validation {
    condition     = contains(["dev", "test", "prod"], var.env)
    error_message = "env must be dev, test or prod."
  }
}
