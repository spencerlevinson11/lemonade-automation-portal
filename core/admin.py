from django.contrib import admin

from .models import (
    Automation,
    Company,
    PricingCustomer,
    PricingQuote,
    PricingQuoteLine,
    TipEntry,
    ProjectPlanEntry,
    OrderContainer,
    OrderContainerLine,
    OrderContainerDocument,
    OrderContainerImportFile,
    ScheduleActivity,
)


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_email", "owner")
    search_fields = ("name", "contact_email", "owner__username")
    list_filter = ("owner",)
    ordering = ("name",)
    list_per_page = 25


@admin.register(Automation)
class AutomationAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "is_active", "last_run_at", "created_at")
    search_fields = ("name", "company__name")
    list_filter = ("is_active", "company")
    ordering = ("company__name", "name")


@admin.register(PricingCustomer)
class PricingCustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "company")
    search_fields = ("name", "company__name")
    list_filter = ("company",)
    ordering = ("company__name", "name")


@admin.register(PricingQuote)
class PricingQuoteAdmin(admin.ModelAdmin):
    list_display = ("company", "customer", "created_at")
    search_fields = ("customer__name", "company__name")
    list_filter = ("company", "customer")
    ordering = ("-created_at",)


@admin.register(PricingQuoteLine)
class PricingQuoteLineAdmin(admin.ModelAdmin):
    list_display = (
        "company",
        "customer",
        "destination",
        "product_description",
        "price_delivered",
        "pallet_quantity_pieces",
        "include_in_quote",
        "updated_at",
    )
    search_fields = ("customer__name", "destination", "product_description", "company__name")
    list_filter = ("company", "customer", "include_in_quote")
    ordering = ("company__name", "customer__name", "destination", "product_description")


@admin.register(TipEntry)
class TipEntryAdmin(admin.ModelAdmin):
    list_display = ("company", "user", "tip_date", "job_type", "tips_total", "updated_at")
    list_filter = ("company", "job_type", "tip_date")
    search_fields = ("user__username", "notes", "company__name")
    ordering = ("-tip_date", "-updated_at")


@admin.register(ProjectPlanEntry)
class ProjectPlanEntryAdmin(admin.ModelAdmin):
    list_display = (
        "company",
        "project_name",
        "priority_level",
        "risk_factor",
        "estimated_cost",
        "estimated_time_hours",
        "estimated_difficulty",
        "updated_at",
    )
    list_filter = ("company", "priority_level", "risk_factor", "estimated_difficulty")
    search_fields = ("project_name", "notes", "company__name")
    ordering = ("-priority_level", "-updated_at")


class OrderContainerLineInline(admin.TabularInline):
    model = OrderContainerLine
    extra = 0


class OrderContainerDocumentInline(admin.TabularInline):
    model = OrderContainerDocument
    extra = 0


@admin.register(OrderContainer)
class OrderContainerAdmin(admin.ModelAdmin):
    list_display = (
        "company",
        "customer_name",
        "location_name",
        "po_number",
        "assigned_to",
        "status",
        "loading_date",
        "estimated_delivery_date",
        "updated_at",
    )
    list_filter = ("company", "assigned_to")
    search_fields = (
        "customer_name",
        "location_name",
        "po_number",
        "rpc_number",
        "booking_number",
        "bill_of_lading_number",
        "status",
    )
    ordering = ("-updated_at",)
    inlines = [OrderContainerLineInline, OrderContainerDocumentInline]


@admin.register(OrderContainerImportFile)
class OrderContainerImportFileAdmin(admin.ModelAdmin):
    list_display = ("id", "company", "label", "file", "uploaded_by", "uploaded_at")
    list_filter = ("company",)
    search_fields = ("label", "file")
    ordering = ("-uploaded_at",)


@admin.register(ScheduleActivity)
class ScheduleActivityAdmin(admin.ModelAdmin):
    list_display = (
        "company",
        "date",
        "start_time",
        "end_time",
        "title",
        "category",
        "assigned_to",
        "status",
        "updated_at",
    )
    list_filter = ("company", "category", "status", "date")
    search_fields = ("title", "assigned_to", "notes", "company__name")
    ordering = ("-date", "start_time", "-updated_at")


# ---- Global admin branding (no "Lemonade Stand") ----
admin.site.site_header = "Automation Portal Admin"
admin.site.site_title = "Automation Portal"
admin.site.index_title = "Control center for your automations"

