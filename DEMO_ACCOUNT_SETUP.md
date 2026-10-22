# LemonadeStandEx demo mode

This demo uses **existing** accounts with usernames `LemonadeStandEx` and
`Retrieverpackaging` (case insensitive). No new database tables, settings, or
JSONCargo keys are required.

## Behavior
- `LemonadeStandEx`'s Order Tracker shows Retrieverpackaging's live stored
  orders, including archived entries. No records are copied into the demo company.
- Customer names are replaced with stable per-snapshot `Customer 01`, etc.
  Order references, private locations, containers, and proprietary details are
  omitted from the demo view. This is a deliberately narrower demo interface,
  not an exact visual replica of Retriever's dashboard.
- The demo account **cannot invoke JSONCargo**: `Refresh mirrored data` only
  reloads currently stored Retriever results. Tracking updates appear once
  Retrieverpackaging has run tracking. This prevents duplicated calls.
- Status, owner, origin, and ETA changes can be tried in the demo UI. They're
  written only to the current Django session (and never to OrderContainer), so
  refreshing the page keeps the demonstration edits but logging out clears them.
  `Reset demo edits` clears them without logging out.
- The demo retains its own owner suggestions; origin is editable per order.
- The demo account is blocked from normal Order Tracker edit, create, delete,
  sync, archive, export, and document URLs (HTTP 403). Existing non-demo users
  are unchanged. The media endpoint is also blocked for the demo account.
- No JSONCargo API key is assigned to the demo account. **Do not assign one.**

## Validation before exposing login externally
1. Deploy to staging first. Log in as Retrieverpackaging and confirm normal
   editing and tracking still work.
2. Log in as LemonadeStandEx and confirm anonymized orders and no identifiers.
3. Edit status/origin/owner/ETA in the demo, check Retriever's record is unchanged.
4. Log out and back in: the demo edit should have disappeared.
5. Trigger a Retriever tracking sync and refresh demo: verify the latest stored
   API ETA appears, with no demo API request.
6. Attempt direct POST to normal `/automations/orders/sync-jsoncargo/` and
   order edit endpoints while logged in as demo; they should return 403.
7. Review every non-Order-Tracker portal page reachable by the demo user for
   proprietary information before sharing public credentials.

## Limitations
This is a safe *order overview* demo and does not replicate all of the production
Order Tracker's original interface or individual actions. The edit samples are
intentionally limited to status, owner, origin, and ETA. If the exact production
order editor must be demoed, build a dedicated sanitized sandbox, not a mutable
proxy to Retriever's production objects.
