from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0023_ordercontainer_shipping_line_dropdown"),
    ]

    operations = [
        migrations.AddField(
            model_name="ordercontainer",
            name="is_archived",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="ordercontainer",
            name="archived_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
