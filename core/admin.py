from django.contrib import admin
from .models import Company, Automation, PricingCustomer, PricingQuote, PricingQuoteLine



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
    list_filter = ("company", "is_active", "created_at")
    search_fields = ("name", "description", "company__name")
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_per_page = 25

    # Optional: make company clickable instead of name only
    list_display_links = ("name",)
@admin.register(PricingCustomer)
class PricingCustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "company")
    search_fields = ("name", "company__name")
    list_filter = ("company",)


@admin.register(PricingQuote)
class PricingQuoteAdmin(admin.ModelAdmin):
    list_display = ("title", "company", "customer", "updated_at")
    search_fields = ("title", "company__name", "customer__name")
    list_filter = ("company",)


@admin.register(PricingQuoteLine)
class PricingQuoteLineAdmin(admin.ModelAdmin):
    list_display = ("company", "customer", "destination", "product_description", "price_delivered", "pallet_quantity_pieces", "updated_at")
    search_fields = ("customer__name", "destination", "product_description", "company__name")
    list_filter = ("company", "customer")


# ---- Global admin branding (no "Lemonade Stand") ----
admin.site.site_header = "Automation Portal Admin"
admin.site.site_title = "Automation Portal"
admin.site.index_title = "Control center for your automations"
