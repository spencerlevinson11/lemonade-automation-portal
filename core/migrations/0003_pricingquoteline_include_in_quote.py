from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_pricing_models"),
    ]

    operations = [
        migrations.AddField(
            model_name="pricingquoteline",
            name="include_in_quote",
            field=models.BooleanField(default=True),
        ),
    ]
