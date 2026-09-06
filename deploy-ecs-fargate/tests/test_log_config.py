"""Tests for the JSON log formatter.

The thing that actually matters here is the shape of the bytes on stdout, so
these assert against parsed JSON output rather than against formatter
internals.
"""

import json
import logging
from datetime import datetime

import pytest

from log_config import JsonFormatter, configure_logging, dict_config


@pytest.fixture
def formatter():
    return JsonFormatter()


def make_record(msg="hello", level=logging.INFO, args=(), **extra):
    record = logging.LogRecord(
        name="app",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )
    record.__dict__.update(extra)
    return record


def emit(formatter, record):
    return json.loads(formatter.format(record))


class TestStandardFields:
    def test_emits_the_core_fields(self, formatter):
        payload = emit(formatter, make_record("something happened"))

        assert payload["level"] == "INFO"
        assert payload["logger"] == "app"
        assert payload["message"] == "something happened"
        assert "timestamp" in payload

    def test_timestamp_is_iso8601_utc(self, formatter):
        payload = emit(formatter, make_record())

        parsed = datetime.fromisoformat(payload["timestamp"])
        assert parsed.tzinfo is not None
        assert parsed.utcoffset().total_seconds() == 0

    def test_level_name_tracks_the_record(self, formatter):
        payload = emit(formatter, make_record(level=logging.WARNING))

        assert payload["level"] == "WARNING"

    def test_percent_style_arguments_are_interpolated(self, formatter):
        payload = emit(formatter, make_record("hello %s", args=("world",)))

        assert payload["message"] == "hello world"


class TestExtraFields:
    def test_extras_are_merged_into_the_payload(self, formatter):
        payload = emit(formatter, make_record(route="hello", greeted="Brian"))

        assert payload["route"] == "hello"
        assert payload["greeted"] == "Brian"

    def test_standard_record_attributes_are_not_leaked(self, formatter):
        """Only our fields and the `extra` ones; not lineno, module, thread..."""
        payload = emit(formatter, make_record(route="hello"))

        assert set(payload) == {"timestamp", "level", "logger", "message", "route"}

    def test_extras_cannot_overwrite_a_core_field(self, formatter):
        payload = emit(formatter, make_record("real message", level=logging.ERROR))
        assert payload["level"] == "ERROR"

        # Set directly on the record, since `logging` itself rejects an
        # `extra` that shadows a LogRecord attribute.
        record = make_record("real message")
        record.__dict__["logger"] = "impostor"
        assert emit(formatter, record)["logger"] == "app"

    def test_unserialisable_values_degrade_to_their_repr(self, formatter):
        """A bad field must not raise and cost us the whole log line."""

        class Opaque:
            def __repr__(self):
                return "<opaque>"

        payload = emit(formatter, make_record(thing=Opaque()))

        assert payload["thing"] == "<opaque>"


class TestSingleLineOutput:
    """Every record has to be exactly one line, or CloudWatch splits it up."""

    def test_output_contains_no_raw_newline(self, formatter):
        rendered = formatter.format(make_record("line one\nline two"))

        assert "\n" not in rendered
        assert json.loads(rendered)["message"] == "line one\nline two"

    def test_a_traceback_stays_on_one_line(self, formatter):
        try:
            raise ValueError("boom")
        except ValueError:
            record = make_record("it broke")
            record.exc_info = __import__("sys").exc_info()

        rendered = formatter.format(record)

        assert "\n" not in rendered
        payload = json.loads(rendered)
        assert "ValueError: boom" in payload["exception"]
        assert payload["message"] == "it broke"


class TestConfigureLogging:
    @pytest.fixture(autouse=True)
    def restore_root_logger(self):
        root = logging.getLogger()
        handlers, level = list(root.handlers), root.level
        yield
        root.handlers[:] = handlers
        root.setLevel(level)

    def test_installs_a_single_json_handler(self):
        root = configure_logging()

        assert len(root.handlers) == 1
        assert isinstance(root.handlers[0].formatter, JsonFormatter)

    def test_is_idempotent(self):
        """Called once at import and again after gunicorn's dictConfig; calling
        it twice must not double every log line."""
        configure_logging()
        root = configure_logging()

        assert len(root.handlers) == 1

    def test_honours_an_explicit_level(self):
        assert configure_logging("DEBUG").level == logging.DEBUG

    def test_reads_the_level_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "warning")

        assert configure_logging().level == logging.WARNING


class TestDictConfig:
    def test_is_accepted_by_dictconfig(self):
        """gunicorn hands this straight to logging.config.dictConfig."""
        import logging.config

        logging.config.dictConfig(dict_config("INFO"))

    def test_routes_gunicorn_loggers_to_the_json_handler(self):
        config = dict_config("INFO")

        for name in ("gunicorn.error", "gunicorn.access"):
            assert config["loggers"][name]["handlers"] == ["stdout"]
            # propagate off, or gunicorn's own handlers duplicate every line.
            assert config["loggers"][name]["propagate"] is False

        assert config["handlers"]["stdout"]["formatter"] == "json"
        assert config["formatters"]["json"]["()"] is JsonFormatter

    def test_does_not_disable_existing_loggers(self):
        """The app's logger exists before gunicorn applies this."""
        assert dict_config("INFO")["disable_existing_loggers"] is False
