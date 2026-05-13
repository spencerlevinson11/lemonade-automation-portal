from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests


JSONCARGO_BASE_URL = os.getenv("JSONCARGO_BASE_URL", "https://api.jsoncargo.com").rstrip("/")


@dataclass
class JsonCargoError:
    status_code: int
    message: str
    payload: Optional[Dict[str, Any]] = None


def _env_int(name: str, default: int) -> int:
    """Read an integer env var safely."""
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def fetch_container_tracking(
    *,
    container_number: str,
    api_key: str,
    shipping_line: str | None = None,
    timeout: int | None = None,
    max_retries: int | None = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[JsonCargoError]]:
    """Fetch container tracking info from JSONCargo.

    Per JSONCargo docs, the container endpoint is:
      GET /api/v1/containers/{tracking_number}?shipping_line={shipping_line}
    Auth header:
      x-api-key: <key>
    """

    container_number = (container_number or "").strip()
    if not container_number:
        return None, JsonCargoError(status_code=400, message="Missing tracking number")

    # JSONCargo occasionally takes longer than 30 seconds for some carriers.
    # Keep these configurable in Render without needing a code change.
    if timeout is None:
        timeout = _env_int("JSONCARGO_TIMEOUT", 90)
    if max_retries is None:
        max_retries = _env_int("JSONCARGO_MAX_RETRIES", 2)
    max_retries = max(0, int(max_retries))

    headers = {
        "x-api-key": api_key,
        "Accept": "application/json",
    }
    params: Dict[str, str] = {}
    if shipping_line:
        params["shipping_line"] = str(shipping_line).strip()

    url = f"{JSONCARGO_BASE_URL}/api/v1/containers/{container_number}"

    last_exc: requests.RequestException | None = None
    for attempt in range(max_retries + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            break
        except requests.RequestException as e:
            last_exc = e
            if attempt >= max_retries:
                return None, JsonCargoError(
                    status_code=0,
                    message=f"Request error after {attempt + 1} attempt(s): {e}",
                )
            # Small backoff before retrying transient timeouts/network errors.
            time.sleep(min(2 ** attempt, 5))
    else:  # defensive; the loop should always return or break
        return None, JsonCargoError(status_code=0, message=f"Request error: {last_exc}")

    try:
        data = resp.json()
    except Exception:
        data = None

    if resp.status_code != 200:
        msg = "Unknown error"
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("title") or err.get("message") or msg
        return None, JsonCargoError(status_code=resp.status_code, message=msg, payload=data if isinstance(data, dict) else None)

    if not isinstance(data, dict):
        return None, JsonCargoError(status_code=500, message="Unexpected JSON response", payload=None)

    return data, None

