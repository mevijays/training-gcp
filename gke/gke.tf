// service account for gke
resource "google_service_account" "gkesa" {
  account_id   = "gke-sa"
  display_name = "gke-sa"
}
  
resource "google_project_iam_binding" "project" {
  project = var.project_id
  role    = "roles/editor"

  members = [
    "serviceAccount:${google_service_account.gkesa.email}",
  ]
  depends_on = [
    google_service_account.gkesa
  ]
}
  
resource "google_container_cluster" "primary" {
  name                     = "${var.cluster_name}-${random_id.randhex.hex}"
  location                 = var.k8s_region
  remove_default_node_pool = false
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
    enabled = false
  }
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = "10.10.0.0/28"
    master_global_access_config {
      enabled = true
    }
  }
 node_config {
    preemptible     = true
    machine_type    = var.node_size
    disk_size_gb    = "60"
    disk_type       = "pd-standard"
    service_account = google_service_account.gkesa.email
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
    tags = ["gke-node"]
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
