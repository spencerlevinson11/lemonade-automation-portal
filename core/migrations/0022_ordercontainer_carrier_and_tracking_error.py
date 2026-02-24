from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0021_tracking_update_kind_note"),
    ]

    operations = [
        migrations.AddField(
            model_name="ordercontainer",
            name="carrier",
            field=models.CharField(blank=True, max_length=64),
        ),
    ]
