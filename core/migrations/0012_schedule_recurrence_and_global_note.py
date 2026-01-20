from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_schedule_activity"),
    ]

    operations = [
        migrations.AddField(
            model_name="scheduleactivity",
            name="is_recurring",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="scheduleactivity",
            name="repeat_every",
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="scheduleactivity",
            name="repeat_unit",
            field=models.CharField(
                choices=[("days", "Days"), ("weeks", "Weeks"), ("months", "Months")],
                default="weeks",
                max_length=8,
            ),
        ),
        migrations.AddField(
            model_name="scheduleactivity",
            name="repeat_until",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name="ScheduleGlobalNote",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("notes", models.TextField(blank=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "company",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="schedule_global_note",
                        to="core.company",
                    ),
                ),
            ],
        ),
    ]
