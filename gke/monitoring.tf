# Log-based metrics for GKE deployment uptime monitoring
# This configuration creates metrics to track deployment availability in the '${var.target_namespace}' namespace

# Log metric to track deployment availability/readiness events
resource "google_logging_metric" "deployment_availability" {
  name   = "gke_deployment_availability_${var.target_namespace}_namespace"
  filter = "resource.type=\"k8s_container\" AND resource.labels.namespace_name=\"${var.target_namespace}\" AND (jsonPayload.reason=\"SuccessfulCreate\" OR jsonPayload.reason=\"Failed\" OR textPayload:\"readiness probe failed\" OR textPayload:\"readiness probe succeeded\")"

  label_extractors = {
    deployment = "EXTRACT(resource.labels.pod_name)"
    namespace  = "EXTRACT(resource.labels.namespace_name)"
  }

  metric_descriptor {
    metric_kind  = "GAUGE"
    value_type   = "BOOL"
    unit         = "1"
    display_name = "GKE Deployment Availability - ${title(var.target_namespace)} Namespace"
  }

  value_extractor = "EXTRACT(jsonPayload.reason=\"SuccessfulCreate\" OR NOT (jsonPayload.reason=\"Failed\" OR textPayload:\"readiness probe failed\"))"
}

# Log metric to track deployment replica readiness ratio
resource "google_logging_metric" "deployment_replica_readiness" {
  name   = "gke_deployment_replica_readiness_${var.target_namespace}_namespace"
  filter = "resource.type=\"k8s_container\" AND resource.labels.namespace_name=\"${var.target_namespace}\" AND (jsonPayload.involvedObject.kind=\"Deployment\" OR jsonPayload.involvedObject.kind=\"ReplicaSet\") AND (jsonPayload.reason:\"ScalingReplicaSet\" OR textPayload:\"replica\")"

  label_extractors = {
    deployment = "EXTRACT(jsonPayload.involvedObject.name)"
    namespace  = "EXTRACT(resource.labels.namespace_name)"
  }

  metric_descriptor {
    metric_kind  = "GAUGE"
    value_type   = "INT64"
    unit         = "1"
    display_name = "GKE Deployment Replica Readiness - ${title(var.target_namespace)} Namespace"
  }

  value_extractor = "1"
}

# Log metric for pod readiness in target namespace
resource "google_logging_metric" "pod_readiness_target_namespace" {
  name   = "gke_pod_readiness_${var.target_namespace}_namespace"
  filter = "resource.type=\"k8s_pod\" AND resource.labels.namespace_name=\"${var.target_namespace}\" AND (jsonPayload.reason=\"Started\" OR jsonPayload.reason=\"Killing\" OR jsonPayload.reason=\"FailedMount\" OR textPayload:\"Pod readiness changed\")"

  label_extractors = {
    pod_name  = "EXTRACT(resource.labels.pod_name)"
    namespace = "EXTRACT(resource.labels.namespace_name)"
  }

  metric_descriptor {
    metric_kind  = "GAUGE"
    value_type   = "BOOL"
    unit         = "1"
    display_name = "GKE Pod Readiness - ${title(var.target_namespace)} Namespace"
  }

  value_extractor = "EXTRACT(jsonPayload.reason=\"Started\")"
}

# Service Level Objective (SLO) for 90% deployment availability
resource "google_monitoring_slo" "deployment_availability_slo" {
  service      = google_monitoring_service.gke_service.service_id
  slo_id       = "deployment-availability-slo"
  display_name = "GKE Deployment Availability SLO (90%)"

  goal                = var.slo_availability_target # 90% availability target
  rolling_period_days = var.slo_rolling_period_days

  # Use request-based SLI for deployment availability monitoring
  request_based_sli {
    good_total_ratio {
      total_service_filter = "resource.type=\"k8s_container\" AND resource.labels.namespace_name=\"${var.target_namespace}\""
      good_service_filter  = "resource.type=\"k8s_container\" AND resource.labels.namespace_name=\"${var.target_namespace}\" AND NOT (jsonPayload.reason=\"Failed\" OR textPayload:\"readiness probe failed\")"
    }
  }
}

# Monitoring service definition for GKE deployments
resource "google_monitoring_service" "gke_service" {
  service_id   = "gke-deployments-${var.target_namespace}-namespace"
  display_name = "GKE Deployments - ${title(var.target_namespace)} Namespace"

  basic_service {
    service_type = "GKE_SERVICE"
    service_labels = {
      project_id     = var.project_id
      location       = var.k8s_region
      cluster_name   = "${var.cluster_name}-${random_id.randhex.hex}"
      namespace_name = var.target_namespace
    }
  }
}

# Alerting policy for SLO burn rate (when error budget is being consumed too quickly)
resource "google_monitoring_alert_policy" "slo_burn_rate_alert" {
  display_name = "GKE Deployment SLO Burn Rate Alert - ${title(var.target_namespace)} Namespace"
  combiner     = "OR"

  conditions {
    display_name = "SLO burn rate too high"

    condition_threshold {
      filter          = "select_slo_burn_rate(\"${google_monitoring_slo.deployment_availability_slo.name}\", \"7d\")"
      duration        = "300s"
      comparison      = "COMPARISON_GREATER_THAN"
      threshold_value = 2.0 # Alert when burn rate > 2x (consuming error budget 2x faster than normal)

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_RATE"
      }
    }
  }

  documentation {
    content   = <<-EOT
    This alert fires when the deployment availability SLO burn rate exceeds 2x the normal rate.
    This means the 10% error budget is being consumed faster than expected.
    
    Investigate:
    1. Check deployment status in '${var.target_namespace}' namespace
    2. Review pod readiness and health
    3. Check for recent deployments or configuration changes
    4. Monitor resource utilization and scaling events
    EOT
    mime_type = "text/markdown"
  }

  alert_strategy {
    auto_close = "604800s" # Auto close after 7 days
  }

  # Add notification channels here if needed
  # notification_channels = [
  #   google_monitoring_notification_channel.email.name
  # ]
}

# Optional: Custom metric for tracking deployment uptime percentage
resource "google_logging_metric" "deployment_uptime_percentage" {
  name   = "gke_deployment_uptime_percentage_${var.target_namespace}_namespace"
  filter = "resource.type=\"gke_container\" AND resource.labels.namespace_name=\"${var.target_namespace}\" AND jsonPayload.involvedObject.kind=\"Deployment\""

  label_extractors = {
    deployment_name = "EXTRACT(jsonPayload.involvedObject.name)"
    namespace       = "EXTRACT(resource.labels.namespace_name)"
  }

  metric_descriptor {
    metric_kind  = "GAUGE"
    value_type   = "DOUBLE"
    unit         = "1"
    display_name = "GKE Deployment Uptime Percentage - ${title(var.target_namespace)} Namespace"
  }

  # Calculate uptime as ratio of ready replicas to desired replicas
  value_extractor = "EXTRACT(jsonPayload.involvedObject.status.readyReplicas / jsonPayload.involvedObject.status.replicas)"
}