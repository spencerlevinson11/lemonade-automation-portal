from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_projectplanentry"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # --- DATABASE: add columns only if missing ---
            database_operations=[
                migrations.RunSQL(
                    sql="""
                    ALTER TABLE core_projectplanentry
                        ADD COLUMN IF NOT EXISTS weeks_to_complete integer NULL;
                    ALTER TABLE core_projectplanentry
                        ADD COLUMN IF NOT EXISTS completed boolean NOT NULL DEFAULT false;
                    ALTER TABLE core_projectplanentry
                        ADD COLUMN IF NOT EXISTS completed_at timestamptz NULL;
                    """,
                    reverse_sql=migrations.RunSQL.noop,
                ),
            ],

            # --- STATE: normal Django AddField ops ---
            state_operations=[
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
                migrations.AddField(
                    model_name="projectplanentry",
                    name="weeks_to_complete",
                    field=models.PositiveIntegerField(
                        blank=True,
                        help_text="If priority is Urgent, number of weeks to complete the project.",
                        null=True,
                    ),
                ),
            ],
        ),
    ]
