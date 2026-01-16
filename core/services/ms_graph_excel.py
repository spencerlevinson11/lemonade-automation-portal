from __future__ import annotations

import base64
import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import msal
import requests
from django.conf import settings
from django.utils import timezone

from core.models import MicrosoftGraphToken


GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphError(RuntimeError):
    pass


@dataclass(frozen=True)
class DriveItemRef:
    drive_id: str
    item_id: str


def _require_setting(name: str) -> str:
    val = getattr(settings, name, None)
    if not val:
        raise GraphError(f"Missing required setting: {name}")
    return str(val)


def build_msal_app() -> msal.ConfidentialClientApplication:
    client_id = _require_setting("MICROSOFT_GRAPH_CLIENT_ID")
    client_secret = _require_setting("MICROSOFT_GRAPH_CLIENT_SECRET")
    tenant_id = getattr(settings, "MICROSOFT_GRAPH_TENANT_ID", "common") or "common"

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    return msal.ConfidentialClientApplication(
        client_id=client_id,
        client_credential=client_secret,
        authority=authority,
    )


def get_authorization_url(state: str) -> str:
    redirect_uri = _require_setting("MICROSOFT_GRAPH_REDIRECT_URI")
    app = build_msal_app()
    scopes = ["Files.ReadWrite", "offline_access", "User.Read"]
    return app.get_authorization_request_url(
        scopes=scopes,
        state=state,
        redirect_uri=redirect_uri,
        prompt="select_account",
    )


def exchange_code_for_token(code: str) -> Dict[str, Any]:
    redirect_uri = _require_setting("MICROSOFT_GRAPH_REDIRECT_URI")
    app = build_msal_app()
    scopes = ["Files.ReadWrite", "offline_access", "User.Read"]
    result = app.acquire_token_by_authorization_code(
        code=code,
        scopes=scopes,
        redirect_uri=redirect_uri,
    )
    if not isinstance(result, dict) or "access_token" not in result:
        raise GraphError(f"Token exchange failed: {result}")
    return result


def store_token_for_user(user, token_result: Dict[str, Any]) -> None:
    access_token = token_result.get("access_token")
    refresh_token = token_result.get("refresh_token")
    expires_in = int(token_result.get("expires_in") or 0)
    if not access_token or not refresh_token or expires_in <= 0:
        raise GraphError("Missing required token fields (access_token/refresh_token/expires_in)")

    expires_at = timezone.now() + dt.timedelta(seconds=expires_in - 60)
    MicrosoftGraphToken.objects.update_or_create(
        user=user,
        defaults={
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_at": expires_at,
        },
    )


def _refresh_access_token(token: MicrosoftGraphToken) -> str:
    app = build_msal_app()
    scopes = ["Files.ReadWrite", "offline_access", "User.Read"]
    result = app.acquire_token_by_refresh_token(token.refresh_token, scopes=scopes)
    if not isinstance(result, dict) or "access_token" not in result:
        raise GraphError(f"Token refresh failed: {result}")

    access_token = result.get("access_token")
    refresh_token = result.get("refresh_token") or token.refresh_token
    expires_in = int(result.get("expires_in") or 0)
    expires_at = timezone.now() + dt.timedelta(seconds=max(expires_in - 60, 60))

    token.access_token = access_token
    token.refresh_token = refresh_token
    token.expires_at = expires_at
    token.save(update_fields=["access_token", "refresh_token", "expires_at", "updated_at"])
    return access_token


def get_access_token_for_user(user) -> str:
    try:
        token = user.ms_graph_token
    except Exception:
        raise GraphError("Microsoft account not connected yet")

    if token.is_expired():
        return _refresh_access_token(token)
    return token.access_token


def _headers(access_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }


def _share_id_from_url(url: str) -> str:
    # Graph expects: u!{base64url(share_url)}
    b = base64.urlsafe_b64encode(url.encode("utf-8")).decode("utf-8")
    b = b.rstrip("=")
    return "u!" + b


def resolve_drive_item_from_share_url(access_token: str, share_url: str) -> DriveItemRef:
    share_id = _share_id_from_url(share_url)
    url = f"{GRAPH_BASE}/shares/{share_id}/driveItem"
    resp = requests.get(url, headers=_headers(access_token), timeout=30)
    if resp.status_code >= 400:
        raise GraphError(f"Graph resolve share failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    drive_id = data.get("parentReference", {}).get("driveId")
    item_id = data.get("id")
    if not drive_id or not item_id:
        raise GraphError(f"Could not resolve driveId/itemId from share link: {data}")
    return DriveItemRef(drive_id=drive_id, item_id=item_id)


def _worksheet_segment(sheet_name: Optional[str]) -> str:
    if sheet_name:
        return f"worksheets('{sheet_name}')"
    return "worksheets/\$\{\$\}"


def get_used_range(access_token: str, ref: DriveItemRef, sheet_name: Optional[str]) -> Dict[str, Any]:
    if sheet_name:
        ws_path = f"worksheets('{sheet_name}')"
    else:
        ws_path = "worksheets/1"  # first worksheet
    url = (
        f"{GRAPH_BASE}/drives/{ref.drive_id}/items/{ref.item_id}/workbook/"
        f"{ws_path}/usedRange(valuesOnly=true)"
    )
    resp = requests.get(url, headers=_headers(access_token), timeout=30)
    if resp.status_code >= 400:
        raise GraphError(f"Graph usedRange failed ({resp.status_code}): {resp.text}")
    return resp.json()


def get_range_values(access_token: str, ref: DriveItemRef, sheet_name: Optional[str], address: str) -> List[List[Any]]:
    if sheet_name:
        ws_path = f"worksheets('{sheet_name}')"
    else:
        ws_path = "worksheets/1"
    url = (
        f"{GRAPH_BASE}/drives/{ref.drive_id}/items/{ref.item_id}/workbook/"
        f"{ws_path}/range(address='{address}')"
    )
    resp = requests.get(url, headers=_headers(access_token), timeout=30)
    if resp.status_code >= 400:
        raise GraphError(f"Graph range GET failed ({resp.status_code}): {resp.text}")
    data = resp.json()
    return data.get("values") or []


def insert_range_down(access_token: str, ref: DriveItemRef, sheet_name: Optional[str], address: str) -> None:
    if sheet_name:
        ws_path = f"worksheets('{sheet_name}')"
    else:
        ws_path = "worksheets/1"
    url = (
        f"{GRAPH_BASE}/drives/{ref.drive_id}/items/{ref.item_id}/workbook/"
        f"{ws_path}/range(address='{address}')/insert"
    )
    payload = {"shift": "Down"}
    resp = requests.post(url, headers=_headers(access_token), json=payload, timeout=30)
    if resp.status_code >= 400:
        raise GraphError(f"Graph range insert failed ({resp.status_code}): {resp.text}")


def set_range_values(access_token: str, ref: DriveItemRef, sheet_name: Optional[str], address: str, values: List[List[Any]]) -> None:
    if sheet_name:
        ws_path = f"worksheets('{sheet_name}')"
    else:
        ws_path = "worksheets/1"
    url = (
        f"{GRAPH_BASE}/drives/{ref.drive_id}/items/{ref.item_id}/workbook/"
        f"{ws_path}/range(address='{address}')"
    )
    payload = {"values": values}
    resp = requests.patch(url, headers=_headers(access_token), json=payload, timeout=30)
    if resp.status_code >= 400:
        raise GraphError(f"Graph range PATCH failed ({resp.status_code}): {resp.text}")


def set_range_fill(access_token: str, ref: DriveItemRef, sheet_name: Optional[str], address: str, argb: str) -> None:
    if sheet_name:
        ws_path = f"worksheets('{sheet_name}')"
    else:
        ws_path = "worksheets/1"
    url = (
        f"{GRAPH_BASE}/drives/{ref.drive_id}/items/{ref.item_id}/workbook/"
        f"{ws_path}/range(address='{address}')/format/fill"
    )
    color = str(argb).strip()
    # Graph expects HTML-style colors (#RRGGBB). Accept ARGB and convert.
    if color and not color.startswith("#") and len(color) == 8:
        color = "#" + color[2:]
    payload = {"color": color}
    resp = requests.patch(url, headers=_headers(access_token), json=payload, timeout=30)
    if resp.status_code >= 400:
        raise GraphError(f"Graph fill PATCH failed ({resp.status_code}): {resp.text}")


def parse_excel_date(value: Any) -> Optional[dt.date]:
    if value is None or value == "":
        return None
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.datetime):
        return value.date()
    # Graph often returns ISO strings for dates
    if isinstance(value, str):
        s = value.strip()
        # try YYYY-MM-DD
        try:
            return dt.date.fromisoformat(s[:10])
        except Exception:
            pass
        # try m/d/yyyy
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})", s)
        if m:
            mm, dd, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if yy < 100:
                yy += 2000
            try:
                return dt.date(yy, mm, dd)
            except Exception:
                return None
    return None


def find_insert_row_for_nld(
    existing_dates: List[Optional[dt.date]],
    new_nld: dt.date,
    start_row: int,
) -> int:
    """Return the 1-indexed worksheet row where the new row should be inserted."""
    for idx, d in enumerate(existing_dates):
        if d and d > new_nld:
            return start_row + idx
    return start_row + len(existing_dates)
