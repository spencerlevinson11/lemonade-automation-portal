# Per-account JSONCargo setup

The existing Render variable `JSONCARGO_API_KEY` is only used by the **non-staff, non-superuser** login whose username is `Retrieverpackaging` (case-insensitive). No other account, including superuser `spencer`, can use it.

For each future customer:
1. Create an ordinary Django user (not staff/superuser), and a `Company` with `owner` set to that user. The Order Tracker currently permits one company per login for its user-facing views.
2. Note the numeric Django user ID in Django admin (or retrieve it using Django shell).
3. Buy a dedicated JSONCargo API key, then add a secret Render environment variable named `JSONCARGO_API_KEY_USER_<USER_ID>` with that key as its value, e.g. `JSONCARGO_API_KEY_USER_42`.
4. Redeploy/restart the Render service to load the new environment variable.
5. Test the customer's single-container Track action and bulk Sync action using that customer's login. An account without a key is denied before any provider request.

Credential rules: never put keys in client-side JavaScript, URLs, logs, Git, or customer-facing pages; do not pass the API key as a subprocess command-line argument. `JSONCARGO_API_KEY` remains a legacy variable for Retrieverpackaging only. All account-specific credentials are server-side.

The management command now requires `--user-id <ID>` and filters its work to that user's company. A superuser cannot supply their own ID to use any key. Existing manual scripts or scheduled tasks calling `jsoncargo_sync_order_tracker` need to be updated to supply the relevant ordinary user's ID.

**Important:** This change prevents a login from sending JSONCargo requests with another login's credential. It does not yet constitute a full commercial multi-tenant security audit across every other portal feature, nor provide self-service key management. Rotate credentials exposed outside the Render secrets environment before production sale.
