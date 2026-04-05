import logging

from django.utils.deprecation import MiddlewareMixin

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(MiddlewareMixin):
    def process_request(self, request):
        logger.debug(f"{request.method} {request.get_full_path()} [user={request.user}]")
