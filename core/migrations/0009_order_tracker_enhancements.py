from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_order_tracking"),
    ]

    operations = [
        migrations.AddField(
            model_name="ordercontainer",
            name="assigned_to",
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AlterField(
            model_name="ordercontainer",
            name="status",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.CreateModel(
            name="OrderContainerDocument",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("file", models.FileField(upload_to="order_docs/")),
                ("label", models.CharField(blank=True, max_length=255)),
                ("uploaded_at", models.DateTimeField(auto_now_add=True)),
                (
                    "container",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="documents",
                        to="core.ordercontainer",
                    ),
                ),
            ],
            options={
                "ordering": ["-uploaded_at", "-id"],
            },
        ),
    ]
