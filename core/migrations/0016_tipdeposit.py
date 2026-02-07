from django.db import migrations, models
import django.db.models.deletion
from django.core.validators import MinValueValidator


class Migration(migrations.Migration):

    dependencies = [
        # TipDeposit is additive and does not alter TipEntry.
        # We depend on the latest migration to keep a linear migration history.
        ("core", "0015_ordercontainer_vessel_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="TipDeposit",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=10, validators=[MinValueValidator(0)])),
                ("deposited_at", models.DateTimeField(auto_now_add=True)),
                (
                    "company",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tip_deposits", to="core.company"),
                ),
                (
                    "user",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tip_deposits", to="auth.user"),
                ),
            ],
            options={
                "ordering": ["-deposited_at"],
            },
        ),
    ]
