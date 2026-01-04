from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views

from core import views as core_views


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
        core_views.custom_logout,
        name="logout",
    ),

    # Main dashboard
    path("", core_views.dashboard, name="dashboard"),

    # Run a specific automation by ID
    path(
        "automations/<int:pk>/run/",
        core_views.run_automation,
        name="run_automation",
    ),

    # Pricing Quotes
    path("automations/pricing/upload/", core_views.pricing_upload_view, name="pricing_upload"),
    path("automations/pricing/customers/", core_views.pricing_customer_list_view, name="pricing_customer_list"),
    path("automations/pricing/customers/<int:customer_id>/", core_views.pricing_customer_edit_view, name="pricing_customer_edit"),
    path("automations/pricing/customers/<int:customer_id>/quote/", core_views.pricing_customer_quote_view, name="pricing_customer_quote"),
    path("automations/tips/", core_views.tip_tracker_view, name="tip_tracker"),
    path("tips/", views.tip_tracker_view, name="tip_tracker"),
    path("tips/delete/<int:entry_id>/", views.tip_entry_delete_view, name="tip_entry_delete"),

    # Bucket Metrics
    path("automations/bucket-metrics/", core_views.bucket_metrics_view, name="bucket_metrics"),
]

# Bucket Projections (optional): only register if the views exist in this deploy
if hasattr(core_views, "bucket_projections_view") and hasattr(core_views, "bucket_projections_export_view"):
    urlpatterns += [
        path("automations/bucket-metrics/projections/", core_views.bucket_projections_view, name="bucket_projections"),
        path("automations/bucket-metrics/projections/export/", core_views.bucket_projections_export_view, name="bucket_projections_export"),
        path("automations/bucket-metrics/projections/export-zip/", core_views.bucket_projections_zip_export_view, name="bucket_projections_export_zip"),
    ]


# Adjusted Prognosis Export (optional)
if hasattr(core_views, "bucket_adjusted_prognosis_export_view"):
    urlpatterns += [
        path(
            "bucket-prognosis-export/",
            core_views.bucket_adjusted_prognosis_export_view,
            name="bucket_adjusted_prognosis_export",
        ),
    ]
