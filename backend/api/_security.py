"""
Shared security helpers for the API layer.

Houses utilities that need to be reusable across multiple routers without
introducing circular imports between, e.g., widgets / setup / chat / apps.
"""

from fastapi import HTTPException, Request


def _require_local_origin(request: Request) -> None:
    """
    Reject cross-site POSTs. The dashboard binds 127.0.0.1:8000 but a
    malicious page in another tab could fetch with Content-Type: text/plain
    (a "simple" CORS request that bypasses preflight) and trigger writes.
    Allow only requests whose Origin / Referer (when present) maps to
    localhost, or browser-less callers (curl) that send neither header.
    """

    def _host(url: str) -> str:
        # crude — just enough to extract netloc from "http://host:port/..."
        if "://" not in url:
            return ""
        rest = url.split("://", 1)[1]
        return rest.split("/", 1)[0].lower()

    LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
    for header in ("origin", "referer"):
        val = request.headers.get(header)
        if not val:
            continue
        host = _host(val)
        # Host portion may include :port — strip it.
        bare = host.rsplit(":", 1)[0] if host.startswith(("127.", "localhost", "[::1]")) else host.split(":")[0]
        if bare not in LOCAL_HOSTS:
            raise HTTPException(
                status_code=403,
                detail=f"cross-site write rejected (origin host: {bare})",
            )
