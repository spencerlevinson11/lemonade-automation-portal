from django.db import migrations


CLASSIC_SOURCE_NAMES = {
    "10 Wide Standard Classic x 2520",
    "10 Wide Standard Classic x 2660",
    "10 Wide Standard Classic x 2800",
    "10 liter classic N6+ 2520",
    "10 liter wide classic + x 2800",
}
CLASSIC_TRACKER_DESCRIPTION = "10 liter wide classic"

NIR_GREY_RPC_DESCRIPTION = "10 liter wide NIR Grey classic x 2800"
NIR_GREY_TRACKER_DESCRIPTION = "10 liter wide classic NIR grey x 2800"


def normalize_existing_order_tracker_lines(apps, schema_editor):
    OrderContainerLine = apps.get_model("core", "OrderContainerLine")

    # NIR grey rename applies to every customer.
    OrderContainerLine.objects.filter(
        item_description=NIR_GREY_RPC_DESCRIPTION
    ).update(item_description=NIR_GREY_TRACKER_DESCRIPTION)

    # Elite/Sunshine matching is intentionally substring-based and
    # case-insensitive to cover their slightly different company names.
    for line in OrderContainerLine.objects.select_related("container").filter(
        item_description__in=CLASSIC_SOURCE_NAMES
    ).iterator():
        customer = (line.container.customer_name or "").lower()
        if "elite" in customer or "sunshine" in customer:
            line.item_description = CLASSIC_TRACKER_DESCRIPTION
            line.save(update_fields=["item_description"])


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0030_rename_n6_plus_2800_order_lines"),
    ]

    operations = [
        migrations.RunPython(
            normalize_existing_order_tracker_lines,
            migrations.RunPython.noop,
        ),
    ]
