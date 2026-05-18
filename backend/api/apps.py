"""
Open-in-app endpoints — launch native macOS apps to specific items.
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from typing import Optional

from api._security import _require_local_origin

router = APIRouter(prefix="/apps")


class OpenAppRequest(BaseModel):
    """Request to open an app with optional context."""
    app: str  # "outlook-email" | "messages" | "outlook-calendar" | "uworld" | "anki"
    ref: str = ""  # item id or query
    context: Optional[dict] = None  # additional context (e.g., phone number)


class OpenAppResponse(BaseModel):
    """Response from open-app endpoint."""
    ok: bool
    error: Optional[str] = None


@router.post("/open", response_model=OpenAppResponse)
def open_app(req: OpenAppRequest, request: Request):
    """Launch a native macOS app to a specific item.

    POST /apps/open
    {
      "app": "outlook-email" | "messages" | "outlook-calendar" | "uworld" | "anki",
      "ref": "<item id or query>",
      "context": { ... optional ... }
    }

    Response:
    { "ok": true } on success
    { "ok": false, "error": "<msg>" } on failure
    """
    _require_local_origin(request)
    # Validate app name
    valid_apps = {"outlook-email", "messages", "outlook-calendar", "uworld", "anki"}
    if req.app not in valid_apps:
        return OpenAppResponse(
            ok=False,
            error=f"Invalid app: {req.app}. Must be one of {valid_apps}"
        )

    try:
        from tools.desktop_apps import open_app
        result = open_app(req.app, req.ref, req.context or {})
        return OpenAppResponse(ok=result.get("ok", False), error=result.get("error"))
    except Exception as e:
        return OpenAppResponse(ok=False, error=str(e))
