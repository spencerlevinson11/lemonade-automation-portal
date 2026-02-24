from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0022_ordercontainer_carrier_and_tracking_error"),
    ]

    operations = [
        migrations.AddField(
            model_name="ordercontainer",
            name="shipping_line_id",
            field=models.CharField(blank=True, choices=[
                ("", "—"),
                ("0010", "Maersk (0010)"),
                ("0011", "Hapag-Lloyd (0011)"),
                ("0012", "HMM (0012)"),
                ("0013", "ONE (0013)"),
                ("0014", "Evergreen (0014)"),
                ("0015", "MSC (0015)"),
                ("0016", "CMA CGM (0016)"),
                ("0017", "COSCO (0017)"),
                ("0018", "ZIM (0018)"),
                ("0019", "Yang Ming (0019)"),
            ], max_length=4),
        ),
    ]
