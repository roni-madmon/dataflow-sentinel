"""Small HTTP client; all scoring remains in the existing FastAPI service."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


class ApiError(RuntimeError):
    pass


def call_api(base_url, path, payload=None, *, timeout=20):
    try:
        parts = urlsplit(base_url)
    except ValueError as exc:
        raise ApiError("Enter a valid API address, such as http://127.0.0.1:8000.") from exc
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ApiError("Enter an http:// or https:// API address.")
    body = None if payload is None else json.dumps(payload, allow_nan=False).encode("utf-8")
    request = Request(base_url.rstrip("/") + path, data=body,
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", "Request rejected.")
        except (ValueError, AttributeError):
            detail = "Request rejected."
        raise ApiError(f"API {exc.code}: {str(detail)[:1500]}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise ApiError("Cannot reach the API. Keep its PowerShell window running and check the address.") from exc
    except ValueError as exc:
        raise ApiError("The API returned an invalid JSON response.") from exc
    if not isinstance(result, dict):
        raise ApiError("The API returned an unexpected response format.")
    return result
