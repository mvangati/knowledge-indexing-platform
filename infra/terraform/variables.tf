variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type    = string
  default = "dev"
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod."
  }
}

variable "project_name" {
  type    = string
  default = "kip"
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "task_cpu" {
  type    = number
  default = 512
}

variable "task_memory" {
  type    = number
  default = 1024
}

variable "image_tag" {
  type    = string
  default = "latest"
}

variable "log_level" {
  type    = string
  default = "INFO"
}

variable "service_desired_count" {
  type    = number
  default = 2
}

variable "service_min_count" {
  type    = number
  default = 1
}

variable "service_max_count" {
  type    = number
  default = 20
}

variable "aurora_instance_count" {
  type    = number
  default = 1
}

variable "db_master_password" {
  type      = string
  sensitive = true
}

variable "tenant_keys_secret" {
  type      = string
  sensitive = true
  default   = "tenant1:change-me-in-prod"
}

variable "alarm_sns_arn" {
  type    = string
  default = ""
}
