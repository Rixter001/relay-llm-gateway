# The Kubernetes cluster (OKE) and its worker node pool.

resource "oci_containerengine_cluster" "relay" {
  compartment_id     = var.compartment_ocid
  name               = var.cluster_name
  kubernetes_version = var.kubernetes_version
  vcn_id             = oci_core_vcn.relay.id
  type               = "BASIC_CLUSTER"

  endpoint_config {
    is_public_ip_enabled = true # reachable only from var.api_allowed_cidr (security list)
    subnet_id            = oci_core_subnet.api.id
  }

  cluster_pod_network_options {
    cni_type = "FLANNEL_OVERLAY"
  }

  options {
    service_lb_subnet_ids = [oci_core_subnet.lb.id]
    kubernetes_network_config {
      pods_cidr     = "10.244.0.0/16"
      services_cidr = "10.96.0.0/16"
    }
  }
}

data "oci_identity_availability_domains" "ads" {
  compartment_id = var.compartment_ocid
}

# Images OKE offers for this cluster; we pick the x86 Oracle Linux 8 image matching the
# Kubernetes version.
data "oci_containerengine_node_pool_option" "relay" {
  node_pool_option_id = oci_containerengine_cluster.relay.id
  compartment_id      = var.compartment_ocid
}

locals {
  k8s_version_number = trimprefix(var.kubernetes_version, "v")
  node_image_id = [
    for source in data.oci_containerengine_node_pool_option.relay.sources : source.image_id
    if length(regexall("Oracle-Linux-8.*-OKE-${local.k8s_version_number}", source.source_name)) > 0
    && length(regexall("aarch64|GPU", source.source_name)) == 0
  ][0]
}

resource "oci_containerengine_node_pool" "relay" {
  compartment_id     = var.compartment_ocid
  cluster_id         = oci_containerengine_cluster.relay.id
  name               = "${var.cluster_name}-nodes"
  kubernetes_version = var.kubernetes_version
  node_shape         = var.node_shape

  node_shape_config {
    ocpus         = var.node_ocpus
    memory_in_gbs = var.node_memory_gbs
  }

  node_config_details {
    size = var.node_count

    # Spread the nodes over every availability domain of the region.
    dynamic "placement_configs" {
      for_each = data.oci_identity_availability_domains.ads.availability_domains
      content {
        availability_domain = placement_configs.value.name
        subnet_id           = oci_core_subnet.nodes.id
      }
    }

    node_pool_pod_network_option_details {
      cni_type = "FLANNEL_OVERLAY"
    }
  }

  node_source_details {
    source_type             = "IMAGE"
    image_id                = local.node_image_id
    boot_volume_size_in_gbs = 100
  }

  initial_node_labels {
    key   = "app"
    value = "relay"
  }
}
