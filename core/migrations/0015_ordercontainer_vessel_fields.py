from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_plantprofile"),
    ]

    operations = [
        migrations.AddField(
            model_name="ordercontainer",
            name="vessel_name",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="ordercontainer",
            name="vessel_mmsi",
            field=models.BigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="ordercontainer",
            name="vessel_imo",
            field=models.BigIntegerField(blank=True, null=True),
        ),
    ]
