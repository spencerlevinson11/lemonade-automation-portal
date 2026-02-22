from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0019_ordercontainerimportfile"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="ordercontainer",
            name="container_number",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.CreateModel(
            name="OrderContainerTrackingUpdate",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("proposed_eta", models.DateField(blank=True, null=True)),
                ("proposed_eta_city", models.CharField(blank=True, max_length=128)),
                ("source_last_updated", models.DateTimeField(blank=True, null=True)),
                ("source_payload", models.JSONField(blank=True, default=dict)),
                (
                    "status",
                    models.CharField(
                        choices=[("pending", "Pending"), ("approved", "Approved"), ("rejected", "Rejected")],
                        default="pending",
                        max_length=16,
                    ),
                ),
                ("decided_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "container",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="tracking_updates",
                        to="core.ordercontainer",
                    ),
                ),
                (
                    "decided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="order_tracking_update_decisions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
