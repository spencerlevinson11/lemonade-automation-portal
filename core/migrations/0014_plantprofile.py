from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_gardenmap"),
    ]

    operations = [
        migrations.CreateModel(
            name="PlantProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scientific_name", models.CharField(max_length=255, unique=True)),
                ("common_name", models.CharField(blank=True, default="", max_length=255)),
                ("hardiness_zones", models.CharField(blank=True, default="", max_length=64)),
                ("sunlight", models.CharField(blank=True, default="", max_length=128)),
                ("water", models.CharField(blank=True, default="", max_length=128)),
                ("nitrogen", models.CharField(blank=True, default="", max_length=128)),
                ("benefits", models.TextField(blank=True, default="")),
                ("drawbacks", models.TextField(blank=True, default="")),
                ("companions_good", models.JSONField(blank=True, default=list)),
                ("companions_bad", models.JSONField(blank=True, default=list)),
                ("source", models.CharField(blank=True, default="", max_length=64)),
                ("raw", models.JSONField(blank=True, default=dict)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
