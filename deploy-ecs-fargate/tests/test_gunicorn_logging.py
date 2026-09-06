"""Tests for the gunicorn access logger.

These drive `access()` with the same shapes gunicorn passes it -- a response, a
request, a WSGI environ, and a timedelta -- and check the fields that come out
the other side.
"""

import json
import logging
from datetime import timedelta

import pytest
from gunicorn.config import Config

from gunicorn_logging import JsonAccessLogger
from log_config import JsonFormatter


class FakeResponse:
    def __init__(self, status="200 OK", sent=42, headers=()):
        self.status = status
        self.sent = sent
        self.headers = list(headers)


def make_environ(**overrides):
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/hello",
        "QUERY_STRING": "name=Brian",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "RAW_URI": "/hello?name=Brian",
        "REMOTE_ADDR": "10.0.1.7",
        "HTTP_USER_AGENT": "curl/8.7.1",
    }
    environ.update(overrides)
    return environ


@pytest.fixture
def gunicorn_logger():
    cfg = Config()
    cfg.set("accesslog", "-")
    return JsonAccessLogger(cfg)


@pytest.fixture
def access(gunicorn_logger, caplog):
    """Call access() and hand back the fields on the emitted record."""

    def _access(response=None, environ=None, request_time=timedelta(milliseconds=12)):
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="gunicorn.access"):
            # gunicorn sets propagate=False on its loggers, so caplog's handler
            # has to go on the logger itself.
            gunicorn_logger.access_log.addHandler(caplog.handler)
            try:
                gunicorn_logger.access(
                    response or FakeResponse(),
                    None,
                    environ or make_environ(),
                    request_time,
                )
            finally:
                gunicorn_logger.access_log.removeHandler(caplog.handler)
        return caplog.records[0] if caplog.records else None

    return _access


class TestAccessFields:
    def test_records_the_request_line(self, access):
        record = access()

        assert record.event == "access"
        assert record.http_method == "GET"
        assert record.path == "/hello"
        assert record.query == "name=Brian"

    def test_status_is_an_integer(self, access):
        """So that `filter status >= 500` works in Logs Insights."""
        record = access(response=FakeResponse(status="503 Service Unavailable"))

        assert record.status == 503

    def test_status_handles_a_bare_code(self, access):
        assert access(response=FakeResponse(status="204")).status == 204

    def test_unparseable_status_becomes_null_rather_than_raising(self, access):
        assert access(response=FakeResponse(status=None)).status is None

    def test_duration_is_reported_in_milliseconds(self, access):
        record = access(request_time=timedelta(seconds=1, milliseconds=500))

        assert record.duration_ms == 1500.0

    def test_reports_response_size_and_client(self, access):
        record = access(response=FakeResponse(sent=1234))

        assert record.response_bytes == 1234
        assert record.remote_addr == "10.0.1.7"
        assert record.user_agent == "curl/8.7.1"

    def test_empty_query_string_is_null_not_empty(self, access):
        assert access(environ=make_environ(QUERY_STRING="")).query is None

    def test_missing_referer_is_null(self, access):
        assert access().referer is None


class TestRequestId:
    def test_picks_up_the_alb_trace_header(self, access):
        trace = "Root=1-63441c4a-abcdef0123456789abcdef01"
        record = access(environ=make_environ(HTTP_X_AMZN_TRACE_ID=trace))

        assert record.request_id == trace

    def test_is_null_without_a_load_balancer_in_front(self, access):
        assert access().request_id is None


class TestDisabledAccessLog:
    def test_logs_nothing_when_access_logging_is_off(self, caplog):
        logger = JsonAccessLogger(Config())  # no accesslog configured

        with caplog.at_level(logging.INFO, logger="gunicorn.access"):
            logger.access_log.addHandler(caplog.handler)
            try:
                logger.access(FakeResponse(), None, make_environ(), timedelta())
            finally:
                logger.access_log.removeHandler(caplog.handler)

        assert caplog.records == []


class TestRendersAsJson:
    def test_the_emitted_record_formats_to_one_json_line(self, access):
        record = access()

        rendered = JsonFormatter().format(record)

        assert "\n" not in rendered
        payload = json.loads(rendered)
        assert payload["event"] == "access"
        assert payload["status"] == 200
        assert payload["path"] == "/hello"
        assert payload["message"] == "GET /hello 200"
