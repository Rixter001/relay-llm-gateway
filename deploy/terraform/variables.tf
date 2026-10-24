variable "region" {
  description = "OCI region, e.g. eu-paris-1 (keeps data in the EU)."
  type        = string
  default     = "eu-paris-1"
}

variable "compartment_ocid" {
  description = "OCID of the compartment that will contain every resource."
  type        = string
}

variable "cluster_name" {
  description = "Name of the OKE cluster and prefix of the network resources."
  type        = string
  default     = "relay"
}

variable "kubernetes_version" {
  description = "Kubernetes version of the control plane and the nodes (must be offered by OKE)."
  type        = string
  default     = "v1.31.1"
}

variable "vcn_cidr" {
  description = "Address range of the VCN."
  type        = string
  default     = "10.0.0.0/16"
}

variable "node_shape" {
  description = "Compute shape of the worker nodes. x86 by default because CI builds an amd64 image; ARM shapes (VM.Standard.A1.Flex) need a multi-arch image."
  type        = string
  default     = "VM.Standard.E4.Flex"
}

variable "node_ocpus" {
  description = "OCPUs per worker node."
  type        = number
  default     = 2
}

variable "node_memory_gbs" {
  description = "Memory per worker node, in GB (Relay needs about 2 GB per replica)."
  type        = number
  default     = 16
}

variable "node_count" {
  description = "Number of worker nodes."
  type        = number
  default     = 2
}

variable "api_allowed_cidr" {
  description = "Only this range can reach the Kubernetes API endpoint. Set it to your office/VPN range."
  type        = string
}
