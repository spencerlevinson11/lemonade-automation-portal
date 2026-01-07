from django.db import migrations, models


def add_columns_if_missing(apps, schema_editor):
    """
    Add completed, completed_at, weeks_to_complete only if the columns are missing.
    Prevents DuplicateColumn errors if those columns already exist in the DB.
    """
    ProjectPlanEntry = apps.get_model("core", "ProjectPlanEntry")
    table = ProjectPlanEntry._meta.db_table

    existing_cols = set()
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s
            """,
            [table],
        )
        existing_cols = {row[0] for row in cursor.fetchall()}

    # Helper to add a field safely
    def safe_add(field_name):
        if field_name in existing_cols:
            return
        field = ProjectPlanEntry._meta.get_field(field_name)
        schema_editor.add_field(ProjectPlanEntry, field)

    safe_add("weeks_to_complete")
    safe_add("completed")
    safe_add("completed_at")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_projectplanentry"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(add_columns_if_missing, reverse_code=migrations.RunPython.noop),
            ],
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
                    field=models.PositiveIntegerField(blank=True, help_text="If priority is Urgent, number of weeks to complete the project.", null=True),
                ),
            ],
        ),
    ]
