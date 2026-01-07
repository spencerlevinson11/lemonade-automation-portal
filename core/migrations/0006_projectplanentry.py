from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_tipentry_job_type"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="ProjectPlanEntry",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("project_name", models.CharField(max_length=255)),
                ("notes", models.TextField(blank=True)),
                (
                    "estimated_cost",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=12,
                        validators=[MinValueValidator(0)],
                    ),
                ),
                (
                    "estimated_time_hours",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        help_text="Estimated total hours.",
                        max_digits=8,
                        validators=[MinValueValidator(0)],
                    ),
                ),
                (
                    "estimated_difficulty",
                    models.IntegerField(
                        choices=[(1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5")],
                        default=3,
                    ),
                ),
                (
                    "priority_level",
                    models.IntegerField(
                        choices=[(1, "Low"), (2, "Medium"), (3, "High"), (4, "Urgent")],
                        default=2,
                    ),
                ),
                (
                    "risk_factor",
                    models.IntegerField(
                        choices=[(1, "1"), (2, "2"), (3, "3"), (4, "4"), (5, "5")],
                        default=3,
                        help_text="Overall risk factor (1-5).",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="project_plans",
                        to="core.company",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="project_plans",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-priority_level", "-updated_at", "-created_at"],
            },
        ),
    ]
