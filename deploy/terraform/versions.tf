terraform {
  required_version = ">= 1.5"

  required_providers {
    oci = {
      source  = "oracle/oci"
      version = "~> 6.0"
    }
  }
}

# Credentials come from ~/.oci/config (or the OCI_* environment variables), never from
# this repository.
provider "oci" {
  region = var.region
}
