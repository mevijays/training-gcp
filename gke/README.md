# GKE Cluster Monitoring and SLI/SLO Setup

This configuration provides comprehensive monitoring and SLI/SLO setup for GKE cluster deployments with focus on uptime monitoring.

## Features

- **Log-based Metrics**: Automatically tracks deployment availability, replica readiness, and pod health
- **SLO Configuration**: 90% availability target with 10% error budget over 7-day rolling period
- **Alerting**: Automated alerts when SLO burn rate exceeds acceptable thresholds
- **Namespace Scoped**: Monitors all deployments in the specified namespace (default: "app")

## Configuration

### Key Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `cluster_name` | `prod-k8s` | GKE cluster name |
| `target_namespace` | `app` | Namespace to monitor for deployments |
| `slo_availability_target` | `0.9` | SLO target (90% availability) |
| `slo_rolling_period_days` | `7` | Rolling period for SLO calculation |

### Monitoring Components

#### 1. Log Metrics
- **Deployment Availability**: Tracks deployment creation/failure events
- **Replica Readiness**: Monitors replica scaling and readiness
- **Pod Readiness**: Tracks pod start/stop and readiness probe status
- **Uptime Percentage**: Calculates deployment uptime ratio

#### 2. Service Level Objectives (SLO)
- **Target**: 90% availability (10% error budget)
- **Period**: 7-day rolling window
- **Measurement**: Request-based SLI using log data

#### 3. Alerting
- **Burn Rate Alert**: Triggers when error budget consumption exceeds 2x normal rate
- **Documentation**: Includes investigation steps and troubleshooting guidance

## Usage

1. Deploy the GKE cluster with monitoring:
   ```bash
   terraform init
   terraform plan
   terraform apply
   ```

2. Create deployments in the target namespace:
   ```bash
   kubectl create namespace app
   kubectl apply -f your-deployment.yaml -n app
   ```

3. Monitor SLO compliance through Google Cloud Console:
   - Navigate to Monitoring > Services
   - View SLO status and error budget consumption

## Monitoring Dashboard

The configuration creates the following monitoring resources:
- Log-based metrics for deployment tracking
- SLO definition with 90% availability target
- Alert policies for proactive issue detection
- Service definition for organized monitoring

## Error Budget Management

With a 90% SLO target:
- **Allowed downtime**: 10% (16.8 hours per week)
- **Alert threshold**: 2x burn rate (consuming budget 2x faster than normal)
- **Rolling period**: 7 days

## Troubleshooting

When alerts fire, investigate:
1. Check deployment status in target namespace
2. Review pod readiness and health checks
3. Examine recent deployments or configuration changes
4. Monitor resource utilization and scaling events

## Customization

To monitor different namespaces or adjust SLO targets:
1. Update variables in `variables.tf`
2. Run `terraform plan` to preview changes
3. Apply changes with `terraform apply`