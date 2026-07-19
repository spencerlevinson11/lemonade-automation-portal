from django.db import migrations


def create_amd_financial_data_automation(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Company = apps.get_model("core", "Company")
    Automation = apps.get_model("core", "Automation")

    spencer = User.objects.filter(username__iexact="spencer").order_by("id").first()
    if not spencer:
        return

    company = (
        Company.objects.filter(owner=spencer, name__icontains="Retriever Packaging").order_by("id").first()
        or Company.objects.filter(owner=spencer).order_by("id").first()
    )
    if not company:
        return

    Automation.objects.get_or_create(
        company=company,
        name="AMD Financial Data Analysis",
        defaults={
            "description": (
                "Downloads and displays AMD daily Yahoo Finance data from "
                "January 1, 2025 through July 17, 2026."
            ),
            "is_active": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0026_industry_relationship_web")]

    operations = [
        migrations.RunPython(
            create_amd_financial_data_automation,
            migrations.RunPython.noop,
        ),
    ]
