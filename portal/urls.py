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
    path(
        "automations/pricing/customers/<int:customer_id>/",
        core_views.pricing_customer_edit_view,
        name="pricing_customer_edit",
    ),
    path(
        "automations/pricing/customers/<int:customer_id>/quote/",
        core_views.pricing_customer_quote_view,
        name="pricing_customer_quote",
    ),

    # Tip Tracker
    path("automations/tips/", core_views.tip_tracker_view, name="tip_tracker"),
    path("tips/", core_views.tip_tracker_view, name="tip_tracker"),
    path("tips/export/", core_views.tip_tracker_export_excel, name="tip_tracker_export_excel"),
    path("automations/tips/export/", core_views.tip_tracker_export_excel, name="tip_tracker_export_excel"),
    path(
        "tips/delete/<int:entry_id>/",
        core_views.tip_entry_delete_view,
        name="tip_entry_delete",
    ),

    # Project Planner
    path("automations/project-planner/", core_views.project_planner_view, name="project_planner"),
    path(
        "automations/project-planner/complete/<int:pk>/",
        core_views.project_plan_complete_view,
        name="project_plan_complete",
    ),
    path(
        "automations/project-planner/delete/<int:pk>/",
        core_views.project_plan_delete_view,
        name="project_plan_delete",
    ),


    # Schedule Dashboard
    path("automations/schedule/", core_views.schedule_dashboard_view, name="schedule_dashboard"),
    path("automations/schedule/add/", core_views.schedule_activity_add_view, name="schedule_activity_add"),
    path("automations/schedule/notes/", core_views.schedule_global_note_save_view, name="schedule_global_note_save"),
    path("automations/schedule/<int:pk>/edit/", core_views.schedule_activity_edit_view, name="schedule_activity_edit"),
    path("automations/schedule/<int:pk>/delete/", core_views.schedule_activity_delete_view, name="schedule_activity_delete"),
    path("automations/schedule/<int:pk>/toggle-done/", core_views.schedule_activity_toggle_done_view, name="schedule_activity_toggle_done"),


    # Order Tracker
    path("automations/orders/", core_views.order_tracker_view, name="order_tracker"),
    path("automations/orders/archived/", core_views.order_tracker_archived_view, name="order_tracker_archived"),
    path("automations/orders/sync-jsoncargo/", core_views.order_tracker_sync_jsoncargo_view, name="order_tracker_sync_jsoncargo"),
    path(
        "automations/orders/sync-jsoncargo/<str:job_id>/",
        core_views.order_tracker_jsoncargo_sync_progress_view,
        name="order_tracker_jsoncargo_sync_progress",
    ),
    path(
        "automations/orders/sync-jsoncargo/<str:job_id>/status/",
        core_views.order_tracker_jsoncargo_sync_status_view,
        name="order_tracker_jsoncargo_sync_status",
    ),
    path("automations/orders/clear-jsoncargo-updates/", core_views.order_tracker_clear_jsoncargo_updates_view, name="order_tracker_clear_jsoncargo_updates"),
    path("automations/orders/bulk-update/", core_views.order_tracker_bulk_update_view, name="order_tracker_bulk_update"),
    path("automations/orders/reset-checks/", core_views.order_tracker_reset_checks_view, name="order_tracker_reset_checks"),
    path(
        "automations/orders/<int:container_id>/tracker-check/",
        core_views.order_container_set_tracker_checked_view,
        name="order_container_set_tracker_checked",
    ),
    path(
        "automations/orders/recap.docx",
        core_views.order_tracker_recap_docx_view,
        name="order_tracker_recap_docx",
    ),
    path("automations/orders/new/", core_views.order_container_edit_view, name="order_container_new"),
    path(
        "automations/orders/<int:container_id>/",
        core_views.order_container_edit_view,
        name="order_container_edit",
    ),
    path(
        "automations/orders/<int:container_id>/commercial-invoice/",
        core_views.order_container_commercial_invoice_view,
        name="order_container_commercial_invoice",
    ),
    path(
        "automations/orders/<int:container_id>/sync-jsoncargo/",
        core_views.order_container_sync_jsoncargo_view,
        name="order_container_sync_jsoncargo",
    ),
    
    path(
        "automations/orders/<int:container_id>/delete/",
        core_views.order_container_delete_view,
        name="order_container_delete",
    ),

    path(
        "automations/orders/<int:container_id>/toggle-delivered/",
        core_views.order_container_toggle_delivered_view,
        name="order_container_toggle_delivered",
    ),

    path(
        "automations/orders/<int:container_id>/archive/",
        core_views.order_container_archive_view,
        name="order_container_archive",
    ),
    path(
        "automations/orders/<int:container_id>/unarchive/",
        core_views.order_container_unarchive_view,
        name="order_container_unarchive",
    ),

    path(
        "automations/orders/<int:container_id>/tracking/<int:update_id>/approve/",
        core_views.order_container_tracking_approve_view,
        name="order_container_tracking_approve",
    ),
    path(
        "automations/orders/<int:container_id>/tracking/<int:update_id>/reject/",
        core_views.order_container_tracking_reject_view,
        name="order_container_tracking_reject",
    ),


    # Industry Relationship Web
    path("automations/amd-financial-data/", core_views.amd_financial_data_view, name="amd_financial_data"),
    path("automations/industry-relationships/", core_views.industry_relationship_web_view, name="industry_relationship_web"),
    path("automations/industry-relationships/save-positions/", core_views.industry_relationship_positions_save_view, name="industry_relationship_positions_save"),

    # Bucket Metrics
    path("automations/bucket-metrics/", core_views.bucket_metrics_view, name="bucket_metrics"),

    # Permaculture Garden Planner
    path("automations/permaculture/", core_views.permaculture_map_view, name="permaculture_map"),
    path("automations/permaculture/save/", core_views.permaculture_map_save_view, name="permaculture_map_save"),
    path("automations/permaculture/reset/", core_views.permaculture_map_reset_view, name="permaculture_map_reset"),
    path("automations/permaculture/import-excel/", core_views.permaculture_map_import_excel_view, name="permaculture_map_import_excel"),
    path(
        "automations/permaculture/plants/search/",
        core_views.permaculture_plant_search_view,
        name="permaculture_plant_search",
    ),
    path(
        "automations/permaculture/plants/profile/",
        core_views.permaculture_plant_profile_view,
        name="permaculture_plant_profile",
    ),
    path(
        "automations/permaculture/plants/companions/",
        core_views.permaculture_companion_suggest_view,
        name="permaculture_plant_companions",
    ),

    # RPC -> Master Spreadsheet Formatter
    path("automations/rpc-master/", core_views.rpc_master_formatter_view, name="rpc_master_formatter"),
    # Microsoft Graph OAuth
    path("microsoft/connect/", core_views.microsoft_connect_view, name="microsoft_connect"),
    path("microsoft/callback/", core_views.microsoft_callback_view, name="microsoft_callback"),

    # Media (uploaded PDFs, etc.)
    # We serve media through Django so it works on Render without needing a separate
    # web server/static files rule for MEDIA_URL.
    path("media/<path:path>", core_views.protected_media_view, name="protected_media"),

]

# Bucket Projections (optional): only register if the views exist in this deploy
if hasattr(core_views, "bucket_projections_view") and hasattr(core_views, "bucket_projections_export_view"):
    urlpatterns += [
        path(
            "automations/bucket-metrics/projections/",
            core_views.bucket_projections_view,
            name="bucket_projections",
        ),
        path(
            "automations/bucket-metrics/projections/export/",
            core_views.bucket_projections_export_view,
            name="bucket_projections_export",
        ),
        path(
            "automations/bucket-metrics/projections/export-zip/",
            core_views.bucket_projections_zip_export_view,
            name="bucket_projections_export_zip",
        ),
        path(
            "automations/bucket-metrics/projections/adjustments-export/",
            core_views.bucket_adjustments_export_view,
            name="bucket_adjustments_export",
        ),
    ]














































































































































































































































































































































































