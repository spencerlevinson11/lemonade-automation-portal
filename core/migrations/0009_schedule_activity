from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_order_tracking"),
    ]

    operations = [
        migrations.CreateModel(
            name="ScheduleActivity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("date", models.DateField()),
                ("start_time", models.TimeField(blank=True, null=True)),
                ("end_time", models.TimeField(blank=True, null=True)),
                ("title", models.CharField(max_length=160)),
                ("category", models.CharField(choices=[('delivery', 'Delivery'), ('production', 'Production'), ('inventory', 'Inventory'), ('sales', 'Sales'), ('admin', 'Admin'), ('other', 'Other')], default="other", max_length=32)),
                ("assigned_to", models.CharField(blank=True, max_length=80)),
                ("notes", models.TextField(blank=True)),
                ("status", models.CharField(choices=[('planned', 'Planned'), ('done', 'Done'), ('canceled', 'Canceled')], default="planned", max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="schedule_activities", to="core.company")),
            ],
            options={"ordering": ["date", "start_time", "created_at", "id"]},
        ),
    ]
