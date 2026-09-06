"""A gunicorn logger that emits access lines as JSON fields.

gunicorn's default access log is an Apache-style string built from
`access_log_format`. Formatting that string into JSON would just be a second
text format to parse, so instead this subclass skips the template and hands the
atoms to the logger as `extra=` fields, where `JsonFormatter` picks them up.
"""

from gunicorn import glogging


def _status_code(status) -> int | None:
    """gunicorn gives status as `"200 OK"` or `"200"` depending on the worker."""
    if isinstance(status, str):
        status = status.split(None, 1)[0]
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


class JsonAccessLogger(glogging.Logger):
    def access(self, resp, req, environ, request_time):
        if not self.access_log_enabled:
            return

        # None of this can be allowed to raise: a malformed request should not
        # take down the worker that is trying to log it.
        try:
            fields = {
                "event": "access",
                "http_method": environ.get("REQUEST_METHOD"),
                "path": environ.get("PATH_INFO"),
                "query": environ.get("QUERY_STRING") or None,
                "status": _status_code(resp.status),
                "duration_ms": round(request_time.total_seconds() * 1000, 3),
                "response_bytes": getattr(resp, "sent", None),
                "remote_addr": environ.get("REMOTE_ADDR"),
                "user_agent": environ.get("HTTP_USER_AGENT"),
                "referer": environ.get("HTTP_REFERER"),
                # The ALB stamps this on every request it forwards. Carrying it
                # into the log is what lets you line an access record up with
                # the application lines from the same request.
                "request_id": environ.get("HTTP_X_AMZN_TRACE_ID"),
            }
            self.access_log.info(
                "%s %s %s",
                fields["http_method"],
                fields["path"],
                fields["status"],
                extra=fields,
            )
        except Exception:
            self.error("failed to write access log", exc_info=True)
