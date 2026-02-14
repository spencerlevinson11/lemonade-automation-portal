from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_ordercontainer_asap_eta_city"),
    ]

    operations = [
        migrations.AddField(
            model_name="ordercontainer",
            name="requested_date_text",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
