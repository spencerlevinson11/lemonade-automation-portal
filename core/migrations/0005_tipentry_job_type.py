from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_tipentry"),
    ]

    operations = [
        migrations.AddField(
            model_name="tipentry",
            name="job_type",
            field=models.CharField(
                choices=[
                    ("well_bartender", "Well-bartender"),
                    ("bartender", "Bartender"),
                    ("server", "Server"),
                    ("mix_well_server", "Mix of well and serving"),
                    ("mix_bartender_server", "Mix of bartender and serving"),
                ],
                default="bartender",
                max_length=32,
            ),
        ),
    ]
