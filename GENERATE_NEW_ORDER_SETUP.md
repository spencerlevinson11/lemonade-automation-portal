# Generate New Order: enable per company

In Django admin, select the customer's Company and create an active Automation with the **exact name** `Generate New Order` for that company. The same company must also have an active Automation named `Order Tracker` (or `Order Tracking`). The user must be the owner of that Company. This is intentional entitlement gating: no new module is granted to existing accounts automatically.

The dashboard's new automation card uses existing automation navigation, which routes to `/automations/generate-new-order/`.

Submitted orders for real customers create one OrderContainer and its generic OrderContainerLine rows, scoped to the logged-in Company. The PDF is returned as a download response without saving it to the server. The user can see the new order by returning to Order Tracker.

Demo (`LemonadeStandEx`) generates PDFs but stores orders and line items in its Django login session only; no OrderContainer or OrderContainerLine is written. Logging out clears this session. Individual account permissions and demo middleware should still be integration-tested on staging.

Requirements: `reportlab` is added to requirements.txt. No migrations are necessary.

Known limits: line items have 40-row maximum; quantity and unit are printed on PDFs, while the legacy Order Tracker line model has only description, pallets, units per pallet and total units. Editing such an order in the existing tracker can recalculate total units from pallets and units-per-pallet, and the free-form unit label is not stored in the legacy tracker line model. Retaining editable units across existing order-line screens would require a model/schema extension.
