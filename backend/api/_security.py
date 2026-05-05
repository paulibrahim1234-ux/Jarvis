"""
Shared security helpers for the API layer.

Houses utilities that need to be reusable across multiple routers without
introducing circular imports between, e.g., widgets / setup / chat / apps.
"""

from fastapi import HTTPException, Request


def _bare_host(host: str) -> str:
    """Extract the bare hostname/IP from an Origin/Referer host string.

    Handles IPv4 (localhost:8000), IPv6 ([::1]:8000), and bare hosts.
    The old branch on host.startswith() was fragile: it applied rsplit only
    when the prefix matched a local pattern and fell through to split(":")[0]
    for everything else — double-stripping ports on non-local hosts with ports
    and silently comparing the wrong value against LOCAL_HOSTS.
    """
    host = host.strip()
    if not host:
        return ""
    if host.startswith("["):
        # IPv6 bracketed form: "[::1]:8000" → "::1"
        end = host.find("]")
        return host[1:end] if end > 0 else host
    # IPv4 or hostname: strip optional :port suffix unconditionally.
    return host.rsplit(":", 1)[0]


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

    # "::1" (not "[::1]") because _bare_host strips the brackets before comparison.
    LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
    for header in ("origin", "referer"):
        val = request.headers.get(header)
        if not val:
            continue
        host = _host(val)
        # Unified bare-host extraction replaces the old prefix-conditional branch.
        # _bare_host handles IPv4, IPv6 (brackets stripped), and plain hostnames.
        bare = _bare_host(host)
        if bare not in LOCAL_HOSTS:
            raise HTTPException(
                status_code=403,
                detail=f"cross-site write rejected (origin host: {bare})",
            )
