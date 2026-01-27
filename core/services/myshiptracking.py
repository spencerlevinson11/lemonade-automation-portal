from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

import requests


MST_BASE = "https://api.myshiptracking.com/api/v2"


def _auth_headers() -> Dict[str, str]:
    """Build auth headers for MyShipTracking.

    IMPORTANT: store the key in an environment variable on Render.
    """
    api_key = (os.getenv("MYSHIPTRACKING_API_KEY") or "").strip()
    if not api_key:
        return {}
    return {"Authorization": f"Bearer {api_key}"}


def bulk_vessel_status(
    *,
    mmsi_list: List[int] | None = None,
    imo_list: List[int] | None = None,
    timeout_s: int = 10,
) -> Tuple[Optional[List[dict]], Optional[str]]:
    """Fetch latest vessel positions for up to 100 identifiers.

    Returns: (data_list, error_message)

    data_list is the envelope's `data` list on success.
    """
    mmsi_list = [int(x) for x in (mmsi_list or []) if x]
    imo_list = [int(x) for x in (imo_list or []) if x]

    if not mmsi_list and not imo_list:
        return [], None

    headers = _auth_headers()
    if not headers:
        return None, "MyShipTracking API key is not configured. Set MYSHIPTRACKING_API_KEY in your environment."

    params = {"response": "simple"}
    if mmsi_list:
        params["mmsi"] = ",".join(str(x) for x in mmsi_list[:100])
    if imo_list:
        params["imo"] = ",".join(str(x) for x in imo_list[:100])

    url = f"{MST_BASE}/vessel/bulk"
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=timeout_s)
    except Exception as e:
        return None, f"MyShipTracking request failed: {e}"

    if not resp.ok:
        # Try to surface the API's envelope error message
        try:
            payload = resp.json()
            msg = payload.get("message") or resp.text
        except Exception:
            msg = resp.text
        return None, f"MyShipTracking error ({resp.status_code}): {msg}"

    try:
        payload = resp.json()
    except Exception:
        return None, "MyShipTracking returned a non-JSON response."

    if payload.get("status") != "success":
        return None, payload.get("message") or "MyShipTracking returned an error."

    data = payload.get("data")
    if not isinstance(data, list):
        return None, "Unexpected MyShipTracking response format."

    return data, None
