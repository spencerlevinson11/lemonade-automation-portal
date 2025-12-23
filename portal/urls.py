from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views

from core.views import (
    dashboard,
    custom_logout,
    run_automation,
    bucket_metrics_view,
    bucket_projections_view,
    bucket_projections_export_view,
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

    # Pricing Quotes
    path("automations/pricing/upload/", pricing_upload_view, name="pricing_upload"),
    path("automations/pricing/customers/", pricing_customer_list_view, name="pricing_customer_list"),
    path("automations/pricing/customers/<int:customer_id>/", pricing_customer_edit_view, name="pricing_customer_edit"),
    path("automations/pricing/customers/<int:customer_id>/quote/", pricing_customer_quote_view, name="pricing_customer_quote"),

    # Bucket Metrics
    path("automations/bucket-metrics/", bucket_metrics_view, name="bucket_metrics"),

    # NEW: Bucket Projections (separate page + export)
    path("automations/bucket-metrics/projections/", bucket_projections_view, name="bucket_projections"),
    path("automations/bucket-metrics/projections/export/", bucket_projections_export_view, name="bucket_projections_export"),
]
