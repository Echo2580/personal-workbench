import secrets
from urllib.parse import urlsplit
from starlette.responses import JSONResponse


def create_session_token():
    return secrets.token_urlsafe(32)


def error_response(code, message, status=403, details=None, recovery_action=None):
    return JSONResponse(
        {
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "recovery_action": recovery_action,
            },
            "request_id": secrets.token_hex(8),
        },
        status_code=status,
    )


def install_security(app):
    @app.middleware("http")
    async def boundary(request, call_next):
        host = request.headers.get("host", "")
        try:
            parsed = urlsplit("http://" + host)
            valid_host = (
                parsed.hostname == "127.0.0.1"
                and not parsed.username
                and not parsed.password
                and parsed.netloc == host
                and not parsed.path
            )
            if parsed.port is None:
                valid_host = False
        except ValueError:
            valid_host = False
        if not valid_host:
            return error_response("invalid_host", "只允许本机地址访问。")
        origin = request.headers.get("origin")
        fetch_site = request.headers.get("sec-fetch-site")
        if (origin and origin != "http://" + host) or fetch_site == "cross-site":
            return error_response("invalid_origin", "拒绝跨站访问。")
        path = request.url.path
        if path.startswith("/api/v1/") and path != "/api/v1/bootstrap":
            if not secrets.compare_digest(
                request.headers.get("x-workbench-token", ""), app.state.token
            ):
                return error_response("invalid_token", "会话失效，请刷新工作台。")
            if (
                request.method not in ("GET", "HEAD", "OPTIONS")
                and origin != "http://" + host
            ):
                return error_response("invalid_origin", "变更请求需要同源来源。")
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
