# Network for the OKE cluster:
#   api subnet    (public)  Kubernetes API endpoint, reachable only from var.api_allowed_cidr
#   nodes subnet  (private) worker nodes, no public IPs; outbound through NAT
#   lb subnet     (public)  load balancers created by Kubernetes Services

resource "oci_core_vcn" "relay" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = [var.vcn_cidr]
  display_name   = "${var.cluster_name}-vcn"
  dns_label      = "relay"
}

resource "oci_core_internet_gateway" "relay" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.relay.id
  display_name   = "${var.cluster_name}-igw"
}

resource "oci_core_nat_gateway" "relay" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.relay.id
  display_name   = "${var.cluster_name}-nat"
}

# Lets private nodes reach Oracle services (container registry, OKE control plane) without
# going through the internet.
data "oci_core_services" "all" {
  filter {
    name   = "name"
    values = ["All .* Services In Oracle Services Network"]
    regex  = true
  }
}

resource "oci_core_service_gateway" "relay" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.relay.id
  display_name   = "${var.cluster_name}-sgw"
  services {
    service_id = data.oci_core_services.all.services[0].id
  }
}

resource "oci_core_route_table" "public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.relay.id
  display_name   = "${var.cluster_name}-public-rt"
  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_internet_gateway.relay.id
  }
}

resource "oci_core_route_table" "private" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.relay.id
  display_name   = "${var.cluster_name}-private-rt"
  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_nat_gateway.relay.id
  }
  route_rules {
    destination       = data.oci_core_services.all.services[0].cidr_block
    destination_type  = "SERVICE_CIDR_BLOCK"
    network_entity_id = oci_core_service_gateway.relay.id
  }
}

resource "oci_core_security_list" "api" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.relay.id
  display_name   = "${var.cluster_name}-api-sl"

  # kubectl access, restricted to the allowed range.
  ingress_security_rules {
    protocol = "6" # TCP
    source   = var.api_allowed_cidr
    tcp_options {
      min = 6443
      max = 6443
    }
  }
  # Worker nodes talking to the control plane.
  ingress_security_rules {
    protocol = "6"
    source   = var.vcn_cidr
    tcp_options {
      min = 6443
      max = 6443
    }
  }
  ingress_security_rules {
    protocol = "6"
    source   = var.vcn_cidr
    tcp_options {
      min = 12250
      max = 12250
    }
  }
  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }
}

resource "oci_core_security_list" "nodes" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.relay.id
  display_name   = "${var.cluster_name}-nodes-sl"

  # Only traffic from inside the VCN (control plane, load balancers, other nodes).
  ingress_security_rules {
    protocol = "all"
    source   = var.vcn_cidr
  }
  egress_security_rules {
    protocol    = "all"
    destination = "0.0.0.0/0"
  }
}

resource "oci_core_security_list" "lb" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.relay.id
  display_name   = "${var.cluster_name}-lb-sl"

  ingress_security_rules {
    protocol = "6"
    source   = "0.0.0.0/0"
    tcp_options {
      min = 443
      max = 443
    }
  }
  egress_security_rules {
    protocol    = "all"
    destination = var.vcn_cidr
  }
}

resource "oci_core_subnet" "api" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.relay.id
  cidr_block        = cidrsubnet(var.vcn_cidr, 12, 0) # 10.0.0.0/28
  display_name      = "${var.cluster_name}-api"
  dns_label         = "api"
  route_table_id    = oci_core_route_table.public.id
  security_list_ids = [oci_core_security_list.api.id]
}

resource "oci_core_subnet" "nodes" {
  compartment_id             = var.compartment_ocid
  vcn_id                     = oci_core_vcn.relay.id
  cidr_block                 = cidrsubnet(var.vcn_cidr, 8, 10) # 10.0.10.0/24
  display_name               = "${var.cluster_name}-nodes"
  dns_label                  = "nodes"
  prohibit_public_ip_on_vnic = true
  route_table_id             = oci_core_route_table.private.id
  security_list_ids          = [oci_core_security_list.nodes.id]
}

resource "oci_core_subnet" "lb" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.relay.id
  cidr_block        = cidrsubnet(var.vcn_cidr, 8, 20) # 10.0.20.0/24
  display_name      = "${var.cluster_name}-lb"
  dns_label         = "lb"
  route_table_id    = oci_core_route_table.public.id
  security_list_ids = [oci_core_security_list.lb.id]
}
