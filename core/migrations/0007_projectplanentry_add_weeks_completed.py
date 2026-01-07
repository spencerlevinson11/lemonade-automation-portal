from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_projectplanentry"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectplanentry",
            name="weeks_to_complete",
            field=models.PositiveIntegerField(
                blank=True,
                null=True,
                help_text="If priority is Urgent, number of weeks to complete the project.",
            ),
        ),
        migrations.AddField(
            model_name="projectplanentry",
            name="completed",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="projectplanentry",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
