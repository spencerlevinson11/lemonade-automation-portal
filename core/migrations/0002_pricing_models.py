# Generated manually for Pricing models

import decimal
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="PricingCustomer",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pricing_customers", to="core.company")),
            ],
            options={
                "unique_together": {("company", "name")},
            },
        ),
        migrations.CreateModel(
            name="PricingQuote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(default="Pricing Quote", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pricing_quotes", to="core.company")),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="quotes", to="core.pricingcustomer")),
            ],
        ),
        migrations.CreateModel(
            name="PricingQuoteLine",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("destination", models.CharField(max_length=255)),
                ("product_description", models.CharField(max_length=255)),
                ("price_delivered", models.DecimalField(decimal_places=4, default=decimal.Decimal("0.0"), max_digits=10)),
                ("pallet_quantity_pieces", models.IntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="pricing_quote_lines", to="core.company")),
                ("customer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="core.pricingcustomer")),
                ("quote", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="lines", to="core.pricingquote")),
            ],
            options={
                "unique_together": {("company", "customer", "destination", "product_description")},
            },
        ),
    ]
