from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views

from core.views import (
    dashboard,
    custom_logout,
    run_automation,
    bucket_metrics_view,
    pricing_upload_view,
    pricing_customer_list_view,
    pricing_customer_edit_view,
    pricing_customer_quote_view,
)



urlpatterns = [
    path("admin/", admin.site.urls),

    # Auth routes
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="core/login.html"),
        name="login",
    ),
    path(
        "logout/",
        custom_logout,
        name="logout",
    ),

    # Main dashboard
    path("", dashboard, name="dashboard"),

    # Run a specific automation by ID
    path(
        "automations/<int:pk>/run/",
        run_automation,
        name="run_automation",
    ),

    # NEW: Bucket Metrics Automation
    path(
        "automations/bucket-metrics/",
        bucket_metrics_view,
        name="bucket_metrics",
    ),
]
