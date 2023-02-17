// service account for gke
resource "google_service_account" "default" {
  account_id   = "gke-sa"
  display_name = "gke-sa"
}
resource "google_container_cluster" "primary" {
  name                     = "${var.cluster_name}-${random_id.randhex.hex}"
  location                 = var.region
  remove_default_node_pool = true
  disk_size                = 60
  initial_node_count       = 1
  ip_allocation_policy {
    cluster_secondary_range_name  = google_compute_subnetwork.subnet.secondary_ip_range.0.range_name
    services_secondary_range_name = google_compute_subnetwork.subnet.secondary_ip_range.1.range_name
  }
  network    = google_compute_network.gke_vpc.name
  subnetwork = google_compute_subnetwork.subnet.name
  addons_config {
    horizontal_pod_autoscaling {
      disabled = false
    }
    network_policy_config {
      disabled = true
    }
    http_load_balancing {
      disabled = false
    }
    gcp_filestore_csi_driver_config {
      enabled = true
    }
    gce_persistent_disk_csi_driver_config {
      enabled = true
    }
  }
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
  network_policy {
    enabled = true
  }
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = "10.10.0.0/28"
    master_global_access_config {
      enabled = true
    }
  }

  master_authorized_networks_config {
    dynamic "cidr_blocks" {
      for_each = var.authorized_ipv4_cidr_block
      content {
        cidr_block   = format("%s/32", cidr_blocks.value)
        display_name = cidr_blocks.value
      }
    }
  }
}

# Separately Managed Node Pool
resource "google_container_node_pool" "primary_nodes" {
  name       = "${google_container_cluster.primary.name}-node-pool"
  location   = var.region
  cluster    = google_container_cluster.primary.name
  node_count = var.gke_num_nodes
  max_pods_per_node = 100
  autoscaling {
    min_node_count = var.min_node
    max_node_count = var.max_node
  }
  node_config {
    preemptible     = true
    machine_type    = var.node_size
    disk_size_gb    = 60
    service_account = google_service_account.default.email
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
    tags = ["gke-node"]
  }
}
