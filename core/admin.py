from django.contrib import admin

from .models import (
    Automation,
    Company,
    PricingCustomer,
    PricingQuote,
    PricingQuoteLine,
    TipEntry,
    ProjectPlanEntry,
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


# ---- Global admin branding (no "Lemonade Stand") ----
admin.site.site_header = "Automation Portal Admin"
admin.site.site_title = "Automation Portal"
admin.site.index_title = "Control center for your automations"
