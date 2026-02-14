from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0016_tipdeposit"),
    ]

    operations = [
        migrations.AddField(
            model_name="ordercontainer",
            name="requested_asap",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="ordercontainer",
            name="eta_city",
            field=models.CharField(blank=True, max_length=128),
        ),
    ]
