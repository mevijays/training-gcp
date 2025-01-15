from flask import Flask, jsonify, render_template_string, request
from google.cloud import bigquery, pubsub_v1, storage
from google.cloud.container_v1 import ClusterManagerClient
from google.cloud.orchestration.airflow import service_v1
from google.api_core import exceptions
from google.oauth2 import service_account
from kubernetes import client, config
from datetime import datetime
import os
import requests
import urllib3
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# Constants
PROJECT_ID = os.getenv('GOOGLE_CLOUD_PROJECT', 'tflabs')
GKE_CLUSTER = os.getenv('GKE_CLUSTER', 'cluster-1')
GKE_ZONE = os.getenv('GKE_ZONE', 'us-central1-c')
GKE_NAMESPACE = os.getenv('GKE_NAMESPACE', 'kube-system')


# Shared Navigation Template
NAV_TEMPLATE = '''
<nav class="navbar navbar-expand-lg navbar-dark bg-dark">
    <div class="container">
        <span class="navbar-brand mb-0 h1">GCP Explorer</span>
        <div class="collapse navbar-collapse">
            <ul class="navbar-nav">
                <li class="nav-item">
                    <a class="nav-link" href="/gcpstatus/">BigQuery</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="/gcpstatus/topics">Pub/Sub Topics</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="/gcpstatus/subscriptions">Pub/Sub Subscriptions</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="/gcpstatus/gke/deployments">GKE Deployments</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="/gcpstatus/composer">Composer Environments</a>
                </li>
            </ul>
        </div>
    </div>
</nav>
'''

# Dataset listing template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>BigQuery Datasets</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    ''' + NAV_TEMPLATE + '''
    <div class="container mt-4">
        <div class="card">
            <div class="card-header">
                <h4 class="mb-0">BigQuery Datasets</h4>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead class="table-dark">
                            <tr>
                                <th>Dataset ID</th>
                                <th>Project</th>
                                <th>Full Dataset ID</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for dataset in datasets %}
                            <tr>
                                <td><a href="/gcpstatus/tables/{{ dataset.project }}/{{ dataset.dataset_id }}" class="text-decoration-none">{{ dataset.dataset_id }}</a></td>
                                <td>{{ dataset.project }}</td>
                                <td><code>{{ dataset.full_dataset_id }}</code></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

# Tables listing template
TABLES_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Tables in {{ dataset_id }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    ''' + NAV_TEMPLATE + '''
    <div class="container mt-4">
        <nav aria-label="breadcrumb">
            <ol class="breadcrumb">
                <li class="breadcrumb-item"><a href="/gcpstatus/" class="text-decoration-none">Datasets</a></li>
                <li class="breadcrumb-item active">{{ dataset_id }}</li>
            </ol>
        </nav>
        <div class="card">
            <div class="card-header">
                <h4 class="mb-0">Tables in {{ dataset_id }}</h4>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead class="table-dark">
                            <tr>
                                <th>Table ID</th>
                                <th>Type</th>
                                <th>Created</th>
                                <th>Rows</th>
                                <th>Size (GB)</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for table in tables %}
                            <tr>
                                <td><a href="/gcpstatus/schema/{{ project }}/{{ dataset_id }}/{{ table.table_id }}" class="text-decoration-none">{{ table.table_id }}</a></td>
                                <td><span class="badge bg-secondary">{{ table.type }}</span></td>
                                <td>{{ table.created }}</td>
                                <td class="text-end">{{ table.num_rows }}</td>
                                <td class="text-end">{{ table.size_gb }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

# Schema template
SCHEMA_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Schema: {{ table_id }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    ''' + NAV_TEMPLATE + '''
    <div class="container mt-4">
        <nav aria-label="breadcrumb">
            <ol class="breadcrumb">
                <li class="breadcrumb-item"><a href="/gcpstatus/" class="text-decoration-none">Datasets</a></li>
                <li class="breadcrumb-item"><a href="/gcpstatus/tables/{{ project }}/{{ dataset_id }}" class="text-decoration-none">{{ dataset_id }}</a></li>
                <li class="breadcrumb-item active">{{ table_id }}</li>
            </ol>
        </nav>
        <div class="card">
            <div class="card-header">
                <h4 class="mb-0">Schema for {{ project }}.{{ dataset_id }}.{{ table_id }}</h4>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead class="table-dark">
                            <tr>
                                <th>Column Name</th>
                                <th>Data Type</th>
                                <th>Mode</th>
                                <th>Description</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for field in schema %}
                            <tr>
                                <td><code>{{ field.name }}</code></td>
                                <td><span class="badge bg-secondary">{{ field.field_type }}</span></td>
                                <td><span class="badge bg-info">{{ field.mode }}</span></td>
                                <td>{{ field.description or '' }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

# Topics Template
TOPICS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Pub/Sub Topics</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    ''' + NAV_TEMPLATE + '''
    <div class="container mt-4">
        <div class="card">
            <div class="card-header">
                <h4 class="mb-0">Pub/Sub Topics</h4>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead class="table-dark">
                            <tr>
                                <th>Topic Name</th>
                                <th>Full Path</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for topic in topics %}
                            <tr>
                                <td>{{ topic.name.split('/')[-1] }}</td>
                                <td><code>{{ topic.name }}</code></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

# Update Subscription Template
SUBS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Pub/Sub Subscriptions</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    ''' + NAV_TEMPLATE + '''
    <div class="container mt-4">
        <div class="card">
            <div class="card-header">
                <h4 class="mb-0">Pub/Sub Subscriptions</h4>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead class="table-dark">
                            <tr>
                                <th>Subscription Name</th>
                                <th>Topic</th>
                                <th>Push/Pull</th>
                                <th>Message Retention</th>
                                <th>Message Ordering</th>
                                <th>Exactly Once</th>
                                <th>Expiration</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for sub in subscriptions %}
                            <tr>
                                <td>{{ sub.name.split('/')[-1] }}</td>
                                <td><code>{{ sub.topic.split('/')[-1] }}</code></td>
                                <td><span class="badge bg-{{ 'info' if sub.push_config else 'secondary' }}">{{ 'Push' if sub.push_config else 'Pull' }}</span></td>
                                <td>{{ sub.message_retention_duration.seconds | default(604800) }} seconds</td>
                                <td><span class="badge bg-{{ 'success' if sub.enable_message_ordering else 'secondary' }}">{{ 'Enabled' if sub.enable_message_ordering else 'Disabled' }}</span></td>
                                <td><span class="badge bg-{{ 'success' if sub.enable_exactly_once_delivery else 'secondary' }}">{{ 'Enabled' if sub.enable_exactly_once_delivery else 'Disabled' }}</span></td>
                                <td>{{ sub.expiration_policy.ttl.seconds if sub.expiration_policy else 'Never' }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''

# GKE Deployments Template
GKE_DEPLOYMENTS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>GKE Deployments</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    ''' + NAV_TEMPLATE + '''
    <div class="container mt-4">
        <div class="card mb-4">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h4 class="mb-0">Select Namespace</h4>
            </div>
            <div class="card-body">
                <select id="namespaceSelect" class="form-select" aria-label="Select namespace">
                    <option selected value="">Loading namespaces...</option>
                </select>
            </div>
        </div>
        <div class="card">
            <div class="card-header">
                <h4 class="mb-0">GKE Deployments in <span id="currentNamespace">{{ namespace }}</span></h4>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead class="table-dark">
                            <tr>
                                <th>Deployment Name</th>
                                <th>Pods</th>
                                <th>Releases</th>
                                <th>Status</th>
                            </tr>
                        </thead>
                        <tbody id="deploymentsTable">
                            {% for deployment in deployments %}
                            <tr>
                                <td>{{ deployment.name }}</td>
                                <td><a href="/gcpstatus/gke/pods/{{ deployment.name }}?namespace={{ namespace }}" class="text-decoration-none">{{ deployment.pods }}</a></td>
                                <td><a href="/gcpstatus/gke/releases/{{ deployment.name }}?namespace={{ namespace }}" class="text-decoration-none">View Images</a></td>
                                <td><span class="badge bg-{{ 'success' if deployment.status == 'UP' else 'danger' }}">{{ deployment.status }}</span></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        // Load namespaces on page load
        document.addEventListener('DOMContentLoaded', function() {
            fetch('/gcpstatus/gke/namespaces')
                .then(response => response.json())
                .then(data => {
                    const select = document.getElementById('namespaceSelect');
                    select.innerHTML = '';
                    data.namespaces.forEach(ns => {
                        const option = document.createElement('option');
                        option.value = ns;
                        option.textContent = ns;
                        if (ns === '{{ namespace }}') {
                            option.selected = true;
                        }
                        select.appendChild(option);
                    });
                });
        });

        // Handle namespace selection
        document.getElementById('namespaceSelect').addEventListener('change', function() {
            const namespace = this.value;
            window.location.href = `/gcpstatus/gke/deployments?namespace=${namespace}`;
        });
    </script>
</body>
</html>
'''

# Add Pod Details Template
POD_DETAILS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Pods for {{ deployment_name }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    ''' + NAV_TEMPLATE + '''
    <div class="container mt-4">
        <nav aria-label="breadcrumb">
            <ol class="breadcrumb">
                <li class="breadcrumb-item"><a href="/gcpstatus/gke/deployments" class="text-decoration-none">Deployments</a></li>
                <li class="breadcrumb-item active">{{ deployment_name }}</li>
            </ol>
        </nav>
        <div class="card">
            <div class="card-header">
                <h4 class="mb-0">Pods for {{ deployment_name }}</h4>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead class="table-dark">
                            <tr>
                                <th>Pod Name</th>
                                <th>Status</th>
                                <th>Ready</th>
                                <th>Restarts</th>
                                <th>Age</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for pod in pods %}
                            <tr>
                                <td>{{ pod.name }}</td>
                                <td><span class="badge bg-{{ 'success' if pod.status == 'Running' else 'warning' }}">{{ pod.status }}</span></td>
                                <td>{{ pod.ready }}</td>
                                <td>{{ pod.restarts }}</td>
                                <td>{{ pod.age }}</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
'''

# Add Release Details Template
RELEASE_DETAILS_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>Images for {{ deployment_name }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    ''' + NAV_TEMPLATE + '''
    <div class="container mt-4">
        <nav aria-label="breadcrumb">
            <ol class="breadcrumb">
                <li class="breadcrumb-item"><a href="/gcpstatus/gke/deployments" class="text-decoration-none">Deployments</a></li>
                <li class="breadcrumb-item active">{{ deployment_name }}</li>
            </ol>
        </nav>
        <div class="card">
            <div class="card-header">
                <h4 class="mb-0">Container Images for {{ deployment_name }}</h4>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-striped table-hover">
                        <thead class="table-dark">
                            <tr>
                                <th>Container Name</th>
                                <th>Image</th>
                                <th>Image ID</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for container in containers %}
                            <tr>
                                <td>{{ container.name }}</td>
                                <td><code>{{ container.image }}</code></td>
                                <td><code>{{ container.image_id }}</code></td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
'''



COMPOSER_ENVIRONMENT_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Environment Details</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    ''' + NAV_TEMPLATE + '''
    <div class="container">
        <h1 class="mt-5">Environment Details</h1>
        {% if details %}
            <ul class="list-group">
                <li class="list-group-item"><strong>Name:</strong> {{ details.name }}</li>
                <li class="list-group-item"><strong>State:</strong> {{ details.state }}</li>
                <li class="list-group-item"><strong>Create Time:</strong> {{ details.create_time }}</li>
                <li class="list-group-item"><strong>Update Time:</strong> {{ details.update_time }}</li>
                <li class="list-group-item"><strong>Config:</strong> {{ details.config }}</li>
                <li class="list-group-item"><strong>Environment Variables:</strong>
                    <ul class="list-group">
                        {% for key, value in details.env_variables.items() %}
                            <li class="list-group-item">{{ key }}: {{ value }}</li>
                        {% endfor %}
                    </ul>
                </li>
            </ul>
        {% endif %}
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/js/bootstrap.bundle.min.js"></script>
</body>
</html>
'''


COMPOSER_LIST_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Composer Environments</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
</head>
<body>
    """ + NAV_TEMPLATE + """
    <div class="container">
        <h1 class="mt-5">Composer Environments</h1>
        {% if environments %}
            <ul class="list-group">
                {% for env in environments %}
                    <li class="list-group-item">
                        <strong>Name:</strong> <a href="/gcpstatus/environment/{{ project_id }}/{{ location }}/{{ env.name }}">{{ env.name }}</a><br>
                        <strong>State:</strong> {{ env.state }}<br>
                        <strong>Create Time:</strong> {{ env.create_time }}<br>
                        <strong>Update Time:</strong> {{ env.update_time }}
                    </li>
                {% endfor %}
            </ul>
        {% else %}
            <p>No environments found.</p>
        {% endif %}
    </div>
</body>
</html>
"""


@app.route('/gcpstatus/')
def list_datasets():
    try:
        client = bigquery.Client()
        datasets = []
        for dataset in client.list_datasets():
            datasets.append({
                'dataset_id': dataset.dataset_id,
                'project': dataset.project,
                'full_dataset_id': f"{dataset.project}.{dataset.dataset_id}"
            })
        return render_template_string(HTML_TEMPLATE, datasets=datasets)
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/gcpstatus/tables/<project>/<dataset_id>')
def list_tables(project, dataset_id):
    try:
        client = bigquery.Client()
        tables = []
        dataset_ref = client.dataset(dataset_id, project=project)
        
        for table in client.list_tables(dataset_ref):
            table_full = client.get_table(table)
            tables.append({
                'table_id': table.table_id,
                'type': table_full.table_type,
                'created': table_full.created.strftime('%Y-%m-%d %H:%M:%S'),
                'num_rows': f"{table_full.num_rows:,}",
                'size_gb': f"{table_full.num_bytes / 1024**3:.2f}"
            })
            
        return render_template_string(TABLES_TEMPLATE, 
                                   tables=tables,
                                   dataset_id=dataset_id,
                                   project=project)
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/gcpstatus/schema/<project>/<dataset_id>/<table_id>')
def show_schema(project, dataset_id, table_id):
    try:
        client = bigquery.Client()
        table_ref = client.dataset(dataset_id, project=project).table(table_id)
        table = client.get_table(table_ref)
        
        return render_template_string(SCHEMA_TEMPLATE,
                                   project=project,
                                   dataset_id=dataset_id,
                                   table_id=table_id,
                                   schema=table.schema)
    except Exception as e:
        return f"Error: {str(e)}", 500

# New routes for Pub/Sub
@app.route('/gcpstatus/topics')
def list_topics():
    try:
        publisher = pubsub_v1.PublisherClient()
        project_path = f"projects/{PROJECT_ID}"
        topics = []
        for topic in publisher.list_topics(request={"project": project_path}):
            topics.append({
                'name': topic.name
            })
        return render_template_string(TOPICS_TEMPLATE, topics=topics)
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/gcpstatus/subscriptions')
def list_subscriptions():
    try:
        subscriber = pubsub_v1.SubscriberClient()
        project_path = f"projects/{PROJECT_ID}"
        subscriptions = []
        for sub in subscriber.list_subscriptions(request={"project": project_path}):
            subscriptions.append({
                'name': sub.name,
                'topic': sub.topic,
                'push_config': sub.push_config,
                'message_retention_duration': sub.message_retention_duration,
                'enable_message_ordering': sub.enable_message_ordering,
                'enable_exactly_once_delivery': sub.enable_exactly_once_delivery,
                'expiration_policy': sub.expiration_policy
            })
        return render_template_string(SUBS_TEMPLATE, subscriptions=subscriptions)
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/gcpstatus/gke/deployments')
def list_deployments():
    try:
        namespace = request.args.get('namespace', GKE_NAMESPACE)
        config.load_kube_config()
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        
        deployments = []
        deploy_list = apps_v1.list_namespaced_deployment(namespace)
        
        for deploy in deploy_list.items:
            selector = deploy.spec.selector.match_labels
            selector_str = ','.join([f"{k}={v}" for k, v in selector.items()])
            
            pod_list = core_v1.list_namespaced_pod(
                namespace,
                label_selector=selector_str
            )
            
            running_pods = sum(1 for pod in pod_list.items if pod.status.phase == 'Running')
            
            deployments.append({
                'name': deploy.metadata.name,
                'pods': running_pods,
                'status': 'UP' if running_pods > 0 else 'DOWN'
            })
            
        return render_template_string(GKE_DEPLOYMENTS_TEMPLATE, 
                                   deployments=deployments,
                                   namespace=namespace)
    except Exception as e:
        return f"Error: {str(e)}", 500

# Add routes for pod and release details
@app.route('/gcpstatus/gke/pods/<deployment_name>')
def show_pods(deployment_name):
    try:
        namespace = request.args.get('namespace', GKE_NAMESPACE)
        config.load_kube_config()
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        
        # Get deployment's selector
        try:
            deploy = apps_v1.read_namespaced_deployment(deployment_name, namespace)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                return f"Deployment {deployment_name} not found in namespace {namespace}", 404
            raise e
            
        selector = deploy.spec.selector.match_labels
        selector_str = ','.join([f"{k}={v}" for k, v in selector.items()])
        
        pod_list = core_v1.list_namespaced_pod(namespace, label_selector=selector_str)
        
        pods = []
        for pod in pod_list.items:
            containers = pod.status.container_statuses if pod.status.container_statuses else []
            ready_count = sum(1 for c in containers if c.ready)
            total_count = len(containers)
            
            pods.append({
                'name': pod.metadata.name,
                'status': pod.status.phase,
                'ready': f"{ready_count}/{total_count}",
                'restarts': sum(c.restart_count for c in containers),
                'age': pod.metadata.creation_timestamp
            })
            
        return render_template_string(POD_DETAILS_TEMPLATE, 
                                   pods=pods,
                                   deployment_name=deployment_name,
                                   namespace=namespace)
    except Exception as e:
        return f"Error: {str(e)}", 500

@app.route('/gcpstatus/gke/releases/<deployment_name>')
def show_releases(deployment_name):
    try:
        namespace = request.args.get('namespace', GKE_NAMESPACE)
        config.load_kube_config()
        apps_v1 = client.AppsV1Api()
        
        try:
            deploy = apps_v1.read_namespaced_deployment(deployment_name, namespace)
        except client.exceptions.ApiException as e:
            if e.status == 404:
                return f"Deployment {deployment_name} not found in namespace {namespace}", 404
            raise e
            
        containers = []
        for container in deploy.spec.template.spec.containers:
            containers.append({
                'name': container.name,
                'image': container.image,
                'image_id': container.image
            })
            
        return render_template_string(RELEASE_DETAILS_TEMPLATE, 
                                   containers=containers,
                                   deployment_name=deployment_name,
                                   namespace=namespace)
    except Exception as e:
        return f"Error: {str(e)}", 500

# Add route to get namespaces
@app.route('/gcpstatus/gke/namespaces')
def get_namespaces():
    try:
        config.load_kube_config()
        core_v1 = client.CoreV1Api()
        namespaces = [ns.metadata.name for ns in core_v1.list_namespace().items]
        return {'namespaces': namespaces}
    except Exception as e:
        return {'error': str(e)}, 500



def get_gcp_token():
    """Helper function to get GCP access token"""
    import google.auth
    import google.auth.transport.requests
    
    credentials, project = google.auth.default()
    auth_req = google.auth.transport.requests.Request()
    credentials.refresh(auth_req)
    return credentials.token

def list_composer_environments(project_id, location):
    try:
        # Initialize the Composer client
        client = service_v1.EnvironmentsClient()
        
        # Construct the parent path
        parent = f"projects/{project_id}/locations/{location}"
        
        # List environments
        environments = client.list_environments(request={"parent": parent})
        
        # Convert environments to list of dictionaries
        env_list = []
        for env in environments:
            env_list.append({
                "name": env.name.split('/')[-1],
                "state": env.state.name,
                "create_time": str(env.create_time),
                "update_time": str(env.update_time)
            })
        
        return env_list
    
    except exceptions.PermissionDenied:
        return {"error": "Permission denied. Please check your credentials."}
    except Exception as e:
        return {"error": str(e)}

def get_composer_environment_details(project_id, location, environment_name):
    try:
        # Initialize the Composer client
        client = service_v1.EnvironmentsClient()
        
        # Construct the environment path
        name = f"projects/{project_id}/locations/{location}/environments/{environment_name}"
        
        # Get environment details
        environment = client.get_environment(request={"name": name})
        
        # Extract environment variables and configurations
        env_details = {
            "name": environment.name.split('/')[-1],
            "state": environment.state.name,
            "create_time": str(environment.create_time),
            "update_time": str(environment.update_time),
            "config": environment.config,
            "env_variables": environment.config.software_config.env_variables
        }
        
        return env_details
    
    except exceptions.PermissionDenied:
        return {"error": "Permission denied. Please check your credentials."}
    except Exception as e:
        return {"error": str(e)}

def list_dags(project_id, location, environment_name):
    try:
        # Initialize the Composer client
        client = service_v1.EnvironmentsClient()
        
        # Construct the environment path
        name = f"projects/{project_id}/locations/{location}/environments/{environment_name}"
        
        # Get environment details
        environment = client.get_environment(request={"name": name})
        
        # Extract the DAGs from the environment configuration
        dags_prefix = environment.config.dag_gcs_prefix
        
        # List DAGs from the GCS prefix
        dag_list = []
        if dags_prefix:
            # Assuming the DAGs are stored in a GCS bucket
            storage_client = storage.Client()
            bucket_name = dags_prefix.split('/')[2]
            prefix = '/'.join(dags_prefix.split('/')[3:])
            bucket = storage_client.bucket(bucket_name)
            blobs = bucket.list_blobs(prefix=prefix)
            for blob in blobs:
                if blob.name.endswith('.py'):
                    dag_list.append(blob.name.split('/')[-1])
        
        return dag_list
    
    except exceptions.PermissionDenied:
        return {"error": "Permission denied. Please check your credentials."}
    except Exception as e:
        return {"error": str(e)}

@app.route('/gcpstatus/environments/<project_id>/<location>')
def get_environments(project_id, location):
    environments = list_composer_environments(project_id, location)
    return jsonify(environments)

@app.route('/gcpstatus/environment/<project_id>/<location>/<environment_name>')
def environment_details(project_id, location, environment_name):
    try:
        details = get_composer_environment_details(project_id, location, environment_name)
        dags = list_dags(project_id, location, environment_name)
        return render_template_string(COMPOSER_ENVIRONMENT_TEMPLATE, 
                                   details=details,
                                   dags=dags)
    except Exception as e:
        return f"Error: {str(e)}", 500

# Modified route handlers
@app.route('/gcpstatus/composer')
def index():
    project_id = os.getenv('GCP_PROJECT_ID', "tflabs")
    location = os.getenv('GCP_LOCATION', "us-central1")
    
    if not project_id or not location:
        return jsonify({"error": "GCP_PROJECT_ID and GCP_LOCATION environment variables must be set"}), 400
    
    try:
        environments = list_composer_environments(project_id, location)
        return render_template_string(COMPOSER_LIST_TEMPLATE, 
                                   environments=environments, 
                                   project_id=project_id, 
                                   location=location)
    except exceptions.GoogleAPICallError as error:
        return jsonify({"error": str(error)}), 500

# At the bottom of the file after all routes
if __name__ == '__main__':
    print(f"Starting GCP Explorer on port 5000..")
    print(f"Project ID: {PROJECT_ID}")
    print(f"GKE Cluster: {GKE_CLUSTER}")
    print(f"Zone: {GKE_ZONE}")
   
    # List all registered routes
    print("\nRegistered Routes:")
    for rule in app.url_map.iter_rules():
        print(f"  {rule.endpoint}: {rule.rule}")
    
    # Run the Flask application
    app.run(
        host='0.0.0.0',
        port=5000,
        debug=True
    )
