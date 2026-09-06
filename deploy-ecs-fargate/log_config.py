"""Structured JSON logging, on stdout, with no third-party dependencies.

One line of JSON per event. That is the whole trick, and it is worth doing
because of where these logs end up: the awslogs driver ships stdout to
CloudWatch, and CloudWatch Logs Insights parses a JSON line into queryable
fields for free. With plain text you are writing regexes against your own log
format forever; with JSON you can ask

    fields @timestamp, request_id, route, greeted
    | filter level = "ERROR"

...and get an answer. A multi-line log record would be ingested as several
unrelated events, so `json.dumps` escaping newlines is a feature, not an
accident.

This module deliberately imports nothing outside the standard library, so both
the app and gunicorn can share it without dragging a logging framework into
the image.
"""

import json
import logging
import os
import sys
from datetime import UTC, datetime

# Everything the logging module puts on a record by itself. Anything on a
# record that is *not* in here arrived via `extra=` and is therefore ours to
# emit. Derived from a real record rather than hardcoded, so a new attribute in
# a future Python does not start leaking into the output.
_STANDARD_RECORD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__) | {
    "asctime",
    "message",
}


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single line of JSON.

    Fields passed through `extra=` are merged in alongside the standard ones:

        log.info("greeting issued", extra={"route": "hello"})
        {"timestamp": "...", "level": "INFO", ..., "route": "hello"}
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Merge the `extra=` fields. The standard keys above are written first
        # and never overwritten, so a stray extra cannot make "level" mean
        # something else halfway through a log group.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and key not in payload:
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        # default=str so that an unserialisable value degrades to its repr
        # instead of throwing inside the logging call and losing the event.
        return json.dumps(payload, default=str)


def log_level() -> str:
    return os.environ.get("LOG_LEVEL", "INFO").upper()


def dict_config(level: str | None = None) -> dict:
    """A logging.config.dictConfig dict, for gunicorn's `logconfig_dict`.

    gunicorn shallow-merges this over its own defaults, so every top-level key
    it cares about has to be present here.
    """
    level = level or log_level()
    return {
        "version": 1,
        # The app's own loggers already exist by the time gunicorn applies
        # this; disabling them would silence exactly the lines we want.
        "disable_existing_loggers": False,
        "formatters": {"json": {"()": JsonFormatter}},
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json",
            }
        },
        "root": {"handlers": ["stdout"], "level": level},
        "loggers": {
            "gunicorn.error": {
                "handlers": ["stdout"],
                "level": level,
                "propagate": False,
            },
            "gunicorn.access": {
                "handlers": ["stdout"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }


def configure_logging(level: str | None = None) -> logging.Logger:
    """Point the root logger at stdout with the JSON formatter.

    Idempotent: existing root handlers are dropped first, so calling this after
    gunicorn has applied `dict_config` leaves one handler rather than two and
    every line logged once.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level or log_level())
    return root
