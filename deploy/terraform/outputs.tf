output "cluster_id" {
  description = "OCID of the OKE cluster."
  value       = oci_containerengine_cluster.relay.id
}

output "kubeconfig_command" {
  description = "Run this to get a kubeconfig for the cluster, then `helm install` the chart."
  value       = "oci ce cluster create-kubeconfig --cluster-id ${oci_containerengine_cluster.relay.id} --region ${var.region} --token-version 2.0.0 --kube-endpoint PUBLIC_ENDPOINT"
}
