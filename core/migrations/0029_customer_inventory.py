from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def configure_falcon_farms_inventory(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Company = apps.get_model("core", "Company")
    Automation = apps.get_model("core", "Automation")

    user = User.objects.filter(username__iexact="FalconFarms").first()
    if not user:
        return

    company = Company.objects.filter(owner_id=user.id).order_by("id").first()
    if company is None:
        company = Company.objects.create(name="Falcon Farms", owner_id=user.id)

    Automation.objects.get_or_create(
        company_id=company.id,
        name="Inventory Availability",
        defaults={
            "description": "Read-only bucket inventory availability for customer ordering.",
            "is_active": True,
        },
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0028_order_tracker_checkboxes"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CustomerInventoryItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bucket_type", models.CharField(max_length=255)),
                ("quantity_available", models.PositiveIntegerField(default=0)),
                ("display_order", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="inventory_items",
                        to="core.company",
                    ),
                ),
            ],
            options={"ordering": ("display_order", "bucket_type")},
        ),
        migrations.AddConstraint(
            model_name="customerinventoryitem",
            constraint=models.UniqueConstraint(
                fields=("company", "bucket_type"),
                name="unique_inventory_bucket_per_company",
            ),
        ),
        migrations.RunPython(configure_falcon_farms_inventory, migrations.RunPython.noop),
    ]
