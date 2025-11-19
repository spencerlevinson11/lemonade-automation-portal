from django.contrib import admin
from .models import Company, Automation


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ("name", "contact_email", "owner")
    search_fields = ("name", "contact_email")


@admin.register(Automation)
class AutomationAdmin(admin.ModelAdmin):
    list_display = ("name", "company", "is_active", "last_run_at", "created_at")
    list_filter = ("company", "is_active")
    search_fields = ("name", "description")
