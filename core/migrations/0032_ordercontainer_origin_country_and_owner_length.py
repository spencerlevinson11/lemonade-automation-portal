from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0031_normalize_order_tracker_bucket_descriptions")]
    operations = [
        migrations.AlterField(model_name="ordercontainer", name="assigned_to", field=models.CharField(max_length=80, blank=True)),
        migrations.AddField(model_name="ordercontainer", name="origin_country", field=models.CharField(max_length=100, blank=True, help_text="Country where this shipment originates")),
    ]
