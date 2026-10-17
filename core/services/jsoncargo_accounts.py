"""JSONCargo credentials belong to an individual non-admin account.

Legacy JSONCARGO_API_KEY is reserved for username Retrieverpackaging only.
For new customers, set JSONCARGO_API_KEY_USER_<numeric Django user ID> in Render.
Never include or expose API keys in HTTP responses, logs or database rows.
"""
import os
from django.core.exceptions import PermissionDenied


def api_key_for_user(user):
    if not getattr(user, "is_authenticated", False) or user.is_superuser or user.is_staff:
        raise PermissionDenied("JSONCargo tracking is not enabled for this account.")
    user_id = getattr(user, "pk", None)
    if not user_id:
        raise PermissionDenied("JSONCargo tracking is not enabled for this account.")
    if str(user.username).casefold() == "retrieverpackaging":
        key = os.environ.get("JSONCARGO_API_KEY", "").strip()
    else:
        key = os.environ.get(f"JSONCARGO_API_KEY_USER_{int(user_id)}", "").strip()
    if not key:
        raise PermissionDenied("No JSONCargo API key has been assigned to your account.")
    return key
