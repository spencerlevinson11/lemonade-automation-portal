from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0024_ordercontainer_archive"),
    ]

    operations = [
        migrations.CreateModel(
            name="OrderContainerTag",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=64)),
                ("color", models.CharField(default="#2563eb", max_length=7)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("container", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="tags", to="core.ordercontainer")),
            ],
            options={"ordering": ["id"]},
        ),
    ]
