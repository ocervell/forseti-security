import grpc
import time
from metrics import send_metrics_to_stackdriver
from google.cloud.forseti.common.util import logger

LOGGER = logger.get_logger(__name__)

class MetricInterceptor(grpc.ServerInterceptor):

    def __init__(self):
        print("Initializing metric interceptor")
        self.sampler = sampler
        self.exporter = exporter

    def intercept_service(self, continuation, handler_call_details):


def send_metrics(func):
    from functools import wraps
    
    @wraps(func)
    def wrapper(*args, **kw):
        method = None
        service_name = None
        if isinstance(args[4], grpc._server._Context):
            servicer_context = args[4]
           # This gives us <service>/<method name>
            method = servicer_context._rpc_event.request_call_details.method
            service_name, method_name = str(method).rsplit('/')[1::]
        else:
            logger.warning('Cannot derive the service name and method')
        try:
            start_t = time.time()
            result = func(*args, **kw)
            status = 'success'
        except Exception:
            status = 'error'
            raise
        finally:
            resp_time = time.time() - start_t
            send_metrics_to_stackdriver(
                service_name,
                method
                resp_time,
                status)
    return result

