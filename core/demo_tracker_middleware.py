"""Prevent demo account from reaching mutable or sensitive tracker endpoints."""
from django.http import HttpResponseForbidden
from .demo_tracker import is_demo_user


class DemoTrackerIsolationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_demo_user(request.user):
            path = request.path_info.rstrip('/') + '/'
            if path.startswith('/media/'):
                return HttpResponseForbidden('Documents are unavailable in demonstration mode.')
            if path.startswith('/automations/orders/'):
                if path != '/automations/orders/' and not (
                    path.startswith('/automations/orders/demo/edit/') or
                    path == '/automations/orders/demo/action/' or
                    path == '/automations/orders/demo/reset/'
                ):
                    return HttpResponseForbidden('Not available in the demonstration account.')
        return self.get_response(request)
