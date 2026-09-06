"""A small greeting service for the ECS Fargate demo.

Three routes:

    GET /hello?name=Brian    -> {"message": "Hello, Brian!"}
    GET /goodbye?name=Brian  -> {"message": "Goodbye, Brian!"}
    GET /health              -> {"status": "ok"}

The name parameter is optional and defaults to "World". /health exists because
the ALB target group checks it, and a task that fails that check gets killed
and replaced in a loop.
"""

import logging
import os
import uuid

from flask import Flask, g, jsonify, request

from log_config import configure_logging

# One line of JSON per event, on stdout, where the awslogs driver picks it up
# and CloudWatch Logs Insights can query the fields directly. Nothing here
# writes to a file: the container filesystem is not where your logs should
# live.
configure_logging()

app = Flask(__name__)
log = logging.getLogger("app")

DEFAULT_NAME = "World"
MAX_NAME_LENGTH = 64


def requested_name() -> str:
    """Read the name query parameter, with a default and a length cap.

    The cap is not paranoia about injection, since we return JSON rather than
    HTML. It keeps a caller from turning the log group into their notepad.
    """
    name = request.args.get("name", DEFAULT_NAME).strip()
    if not name:
        return DEFAULT_NAME
    return name[:MAX_NAME_LENGTH]


@app.before_request
def assign_request_id():
    """Correlate every line from one request.

    The ALB stamps `X-Amzn-Trace-Id` on everything it forwards, so reusing it
    ties these logs to the access log and to the load balancer's own record of
    the same request. Falls back to a fresh id when running locally, where
    there is no ALB in front.
    """
    g.request_id = request.headers.get("X-Amzn-Trace-Id") or str(uuid.uuid4())


def log_fields(**fields) -> dict:
    """Fields for a structured log line, with the request id always attached.

    Note the key is `greeted` rather than `name`: `logging` refuses an `extra`
    that would shadow an existing LogRecord attribute, and `name` is the
    logger's own.
    """
    return {"request_id": g.get("request_id"), **fields}


@app.get("/hello")
def hello():
    name = requested_name()
    log.info(
        "greeting issued",
        extra=log_fields(event="greeting", route="hello", greeted=name),
    )
    return jsonify(message=f"Hello, {name}!", route="hello")


@app.get("/goodbye")
def goodbye():
    name = requested_name()
    log.info(
        "farewell issued",
        extra=log_fields(event="farewell", route="goodbye", greeted=name),
    )
    return jsonify(message=f"Goodbye, {name}!", route="goodbye")


@app.get("/health")
def health():
    """Cheap and dependency-free, on purpose.

    A health check that calls your database turns one slow dependency into
    every task being replaced at once.

    Deliberately emits no application log line: the target group polls this
    every few seconds per task, forever, and paying to store that in CloudWatch
    buys you nothing. The gunicorn access log still records it, which is where
    to look if you want to prove the health checks are actually arriving.
    """
    return jsonify(status="ok")


@app.get("/")
def index():
    return jsonify(
        service="ecs-fargate-demo",
        routes=["/hello?name=", "/goodbye?name=", "/health"],
    )


@app.errorhandler(404)
def not_found(_error):
    log.warning(
        "route not found",
        extra=log_fields(event="not_found", path=request.path),
    )
    return jsonify(error="not found", routes=["/hello", "/goodbye", "/health"]), 404


# There is deliberately no `@app.errorhandler(Exception)` here. Flask already
# logs unhandled exceptions through `app.logger`, which propagates to the root
# handler configured above, so a traceback arrives as the `exception` field of
# a single JSON event rather than as one CloudWatch line per stack frame. A
# catch-all handler would also swallow 404 and 405, which are answers rather
# than crashes.


if __name__ == "__main__":
    # Local development only. In the container, gunicorn serves this app.
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=True)
