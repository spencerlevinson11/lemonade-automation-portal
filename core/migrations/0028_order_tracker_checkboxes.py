from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0027_amd_financial_data_automation"),
    ]

    operations = [
        migrations.AddField(
            model_name="ordercontainer",
            name="tracker_checked",
            field=models.BooleanField(default=False),
        ),
    ]
