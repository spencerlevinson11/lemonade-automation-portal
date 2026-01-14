from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_projectplanentry_add_weeks_completed"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="OrderContainer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("customer_name", models.CharField(max_length=255)),
                ("location_name", models.CharField(blank=True, max_length=255)),
                ("po_number", models.CharField(blank=True, max_length=64)),
                ("requested_date", models.DateField(blank=True, null=True)),
                ("status", models.CharField(choices=[("planned", "Planned"), ("booked", "Booked"), ("loaded", "Loaded"), ("sailed", "Sailed / In transit"), ("arrived_port", "Arrived (port)"), ("customs", "Customs / Hold"), ("delivered", "Delivered"), ("cancelled", "Cancelled")], default="planned", max_length=32)),
                ("rpc_number", models.CharField(blank=True, max_length=64)),
                ("loading_date", models.DateField(blank=True, null=True)),
                ("etd", models.DateField(blank=True, null=True)),
                ("eta", models.DateField(blank=True, null=True)),
                ("estimated_delivery_date", models.DateField(blank=True, null=True)),
                ("booking_number", models.CharField(blank=True, max_length=128)),
                ("bill_of_lading_number", models.CharField(blank=True, max_length=128)),
                ("notes", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="order_containers", to="core.company")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="created_order_containers", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ["-updated_at", "-created_at"],
            },
        ),
        migrations.CreateModel(
            name="OrderContainerLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("item_description", models.CharField(max_length=255)),
                ("pallets", models.PositiveIntegerField(default=0)),
                ("units_per_pallet", models.PositiveIntegerField(default=0)),
                ("total_units", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("container", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="core.ordercontainer")),
            ],
            options={
                "ordering": ["id"],
            },
        ),
    ]
