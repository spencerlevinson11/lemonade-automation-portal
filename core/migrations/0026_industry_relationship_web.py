from django.db import migrations, models
import django.db.models.deletion


def create_retriever_relationship_automation(apps, schema_editor):
    Company = apps.get_model("core", "Company")
    Automation = apps.get_model("core", "Automation")
    company = (
        Company.objects.filter(name__icontains="Retriever").order_by("id").first()
        or Company.objects.filter(name__icontains="Packaging").order_by("id").first()
    )
    if not company:
        return
    Automation.objects.get_or_create(
        company=company,
        name="Industry Relationship Web",
        defaults={
            "description": "Interactive web for mapping suppliers, customers, owners, backers, and former relationships in the industry.",
            "is_active": True,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0025_ordercontainertag"),
    ]

    operations = [
        migrations.CreateModel(
            name="IndustryRelationshipNode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255)),
                ("kind", models.CharField(choices=[("company", "Company"), ("customer", "Customer"), ("supplier", "Supplier"), ("backer", "Backer / Owner"), ("other", "Other")], default="company", max_length=32)),
                ("notes", models.TextField(blank=True, default="")),
                ("x", models.FloatField(blank=True, null=True)),
                ("y", models.FloatField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="industry_relationship_nodes", to="core.company")),
            ],
            options={
                "ordering": ("name",),
                "unique_together": {("company", "name")},
            },
        ),
        migrations.CreateModel(
            name="IndustryRelationshipEdge",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(default="supplies", max_length=80)),
                ("is_former", models.BooleanField(default=False)),
                ("notes", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("company", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="industry_relationship_edges", to="core.company")),
                ("source", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="outgoing_relationships", to="core.industryrelationshipnode")),
                ("target", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="incoming_relationships", to="core.industryrelationshipnode")),
            ],
            options={
                "ordering": ("source__name", "target__name"),
            },
        ),
        migrations.RunPython(create_retriever_relationship_automation, migrations.RunPython.noop),
    ]
