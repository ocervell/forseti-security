from google.cloud import monitoring
import requests
import os
import time
from google.cloud.forseti.common.util import logger
import time
import random
from opencensus.stats import aggregation as aggregation_module
from opencensus.stats.exporters import stackdriver_exporter as stackdriver
from opencensus.stats import measure as measure_module
from opencensus.stats import stats as stats_module
from opencensus.stats import view as view_module
from opencensus.tags import tag_key as tag_key_module
from opencensus.tags import tag_map as tag_map_module
from opencensus.tags import tag_value as tag_value_module

LOGGER = logger.get_logger(__name__)

FRONTEND_KEY = tag_key_module.TagKey("my.org/keys/frontend")
VIDEO_SIZE_MEASURE = measure_module.MeasureInt(
    "my.org/measure/video_size_test2", "size of processed videos", "By")
VIDEO_SIZE_VIEW_NAME = "my.org/views/video_size_test2"
VIDEO_SIZE_DISTRIBUTION = aggregation_module.DistributionAggregation(
                            [0.0, 16.0 * MiB, 256.0 * MiB])
VIDEO_SIZE_VIEW = view_module.View(VIDEO_SIZE_VIEW_NAME,
                                "processed video size over time",
                                [FRONTEND_KEY],
                                VIDEO_SIZE_MEASURE,
                                VIDEO_SIZE_DISTRIBUTION)

# On GKE, we'll need to `kubernetes` package, but not on GCE
try:
    from kubernetes import client, config
    KUBERNETES_ENABLED=True
except ImportError:
    KUBERNETES_ENABLED=False

metadata_header = {'Metadata-Flavor': 'Google'}

def instance_id():
    r = requests.get("http://metadata.google.internal./computeMetadata/v1/instance/id", headers=metadata_header)
    return r.text

def project_id():
    r = requests.get('http://metadata.google.internal/computeMetadata/v1/project/')
    return r.text()

def zone():
    r = requests.get("http://metadata.google.internal./computeMetadata/v1/instance/zone", headers=metadata_header)
    parts = r.text.split('/')
    return parts[len(parts) - 1]

def cluster_name():
    return os.environ['CLUSTER_NAME'] # cannot be determined from metadata

def container_name():
    return os.environ['CONTAINER_NAME'] # cannot be determined from metadata (HOSTNAME is Pod ID)

def namespace_id():
    config.load_incluster_config()
    v1 = client.CoreV1Api()
    return v1.list_namespace().items[0].metadata.uid

def pod_uid():
    return os.environ['POD_UID']

def setup_stats():
    stats = stats_module.Stats()
    view_manager = stats.view_manager
    stats_recorder = stats.stats_recorder
    exporter = stackdriver.new_stats_exporter(stackdriver.Options(project_id=project_id()))
    view_manager.register_exporter(exporter)
    view_manager.register_view(VIDEO_SIZE_VIEW)

def start_measurement():
    tag_value = tag_value_module.TagValue(1200)
    tag_map = tag_map_module.TagMap()
    tag_map.insert(FRONTEND_KEY, tag_value)
    measure_map = stats_recorder.new_measurement_map()
    return measure_map, tag_map

def end_measurement(measure_map, tag_map):
    measure_map.measure_int_put(VIDEO_SIZE_MEASURE, 25 * MiB)
    measure_map.record(tag_map)

def create_stackdriver_resource(sdclient, resource_type):
    if resource_type == 'gke':
        if not KUBERNETES_ENABLED:
            return None
        return sdclient.resource(
            'gke_container',
            labels={
                'cluster_name': cluster_name(),
                'container_name': container_name(),
                'instance_id': instance_id(),
                'namespace_id': "flask-app",
                'pod_id': pod_uid(),
                'zone': zone(),
            }
        )
    elif resource_type == 'gce':
        return sdclient.resource(
            'gce_instance',
            labels={
                'project_id': project_id(),
                'instance_id': instance_id(),
                'zone': zone()
            }
    else:
        print("Resource type {} is not supported yet.".format(resource_type))
        return None

def send_metrics_to_stackdriver(service_name, method, latency, response_status):
    try:
        sdclient = monitoring.Client(project_id())
        resource = get_stackdriver_resource('gce')
        latency_metric = sdclient.metric(
            type_='custom.googleapis.com/forseti/service_latency_ms',
            labels = {
                'app': 'forseti',
                'service': service_name,
                'method': method
            }
        )
        http_code_metric = sdclient.metric(
            type_='custom.googleapis.com/forseti/service_response_status',
            labels = {
                'app': 'forseti',
                'service': service_name,
                'method': method
            }
        )
        if resource is None:
            LOGGER.warning("Could not retrieve instance metadata. Skipping `send_metrics`.")
            return
        sdclient.write_point(latency_metric, resource, latency * 1000)
        sdclient.write_point(http_code_metric, resource, response_status)
        LOGGER.info("Metric {} pushed to Stackdriver".format(latency_metric))

    except Exception as e:
        LOGGER.exception(e)
        LOGGER.error("Error while sending metrics to Stackdriver: {}".format(str(e)))
