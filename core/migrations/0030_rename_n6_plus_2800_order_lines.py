from django.db import migrations


OLD_NAME = "10 liter wide N6+ x 2800"
NEW_NAME = "10 liter wide classic + x 2800"


def rename_order_tracker_lines(apps, schema_editor):
    OrderContainerLine = apps.get_model("core", "OrderContainerLine")
    OrderContainerLine.objects.filter(item_description=OLD_NAME).update(
        item_description=NEW_NAME
    )


def reverse_rename_order_tracker_lines(apps, schema_editor):
    OrderContainerLine = apps.get_model("core", "OrderContainerLine")
    OrderContainerLine.objects.filter(item_description=NEW_NAME).update(
        item_description=OLD_NAME
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0029_customer_inventory"),
    ]

    operations = [
        migrations.RunPython(
            rename_order_tracker_lines,
            reverse_rename_order_tracker_lines,
        ),
    ]
