# Order Tracker: customer-specific owners and shipment origins

## After deployment

Run `python manage.py migrate` to add the optional `origin_country` column and increase the owner name limit to 80 characters. Existing records are retained.

## Retriever Packaging

The company attached to username `Retrieverpackaging` retains the **Spencer / Jaime** radio choices. Its map continues to use the Netherlands (or a recognized Dutch loading port returned by JSONCargo). No old orders need editing.

## New customers

In **Order Tracker > Add order**, type an owner name in the Owner box, or choose an existing name suggested from *that customer's own orders*. The name is stored on the order and automatically becomes a suggestion/filter for that customer's later orders. This is per-company without creating additional login accounts. Existing names remain available while at least one order uses them.

In each order's detail editor, set **Shipment origin country**. Save the order. Countries are free-text so the country is saved even if the map does not support its coordinates yet. The estimated map currently recognizes common shipping origins from its built-in coordinate list. If a country is blank or not recognized, the map omits that route rather than inventing a Netherlands origin. These are representative map coordinates, not live positions or actual departure ports.

## Scope

No changes were made to JSONCargo credentials, per-company container authorization, database ownership, RPC generation, or unrelated features. For new companies created with no existing orders, the owner list starts empty until they type a name.
