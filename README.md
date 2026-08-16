# lemonade-automation-portal

 
# lemonade-automation-portal

 

## Falcon Farms customer inventory

Migration `0029_customer_inventory` adds a customer-specific bucket inventory feature.

- Superusers can open **Inventory Availability** and add, update, or remove bucket types and available quantities.
- The customer account can open the same automation but receives a read-only view; POST/write requests from non-superusers are rejected server-side.
- During migration, the app looks for the existing username `FalconFarms`. If found, it uses that user's existing company or creates `Falcon Farms`, then creates the `Inventory Availability` automation.
- If the `FalconFarms` account is created after migrations have already run, execute `python manage.py setup_falcon_inventory` once.
