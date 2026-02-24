from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0020_jsoncargo_tracking_updates"),
    ]

    operations = [
        migrations.AddField(
            model_name="ordercontainertrackingupdate",
            name="kind",
            field=models.CharField(choices=[("change", "Change"), ("no_change", "No change")], default="change", max_length=16),
        ),
        migrations.AddField(
            model_name="ordercontainertrackingupdate",
            name="note",
            field=models.TextField(blank=True),
        ),
    ]
