"""Unit tests for the greeting service.

These cover the contract the README publishes and the edge cases in
`requested_name`, which is the only part of the app with any behaviour worth
getting wrong.
"""

import json
import logging

import pytest

from app import DEFAULT_NAME, MAX_NAME_LENGTH
from log_config import JsonFormatter

GREETING_ROUTES = [("/hello", "Hello", "hello"), ("/goodbye", "Goodbye", "goodbye")]


@pytest.mark.parametrize("path,greeting,route", GREETING_ROUTES)
class TestGreetingRoutes:
    """Both greeting routes share one implementation, so they share one suite."""

    def test_defaults_to_world_when_name_is_absent(self, client, path, greeting, route):
        response = client.get(path)

        assert response.status_code == 200
        assert response.json == {
            "message": f"{greeting}, {DEFAULT_NAME}!",
            "route": route,
        }

    def test_uses_the_name_query_parameter(self, client, path, greeting, route):
        response = client.get(path, query_string={"name": "Brian"})

        assert response.status_code == 200
        assert response.json == {"message": f"{greeting}, Brian!", "route": route}

    def test_returns_json(self, client, path, greeting, route):
        response = client.get(path)

        assert response.mimetype == "application/json"

    @pytest.mark.parametrize(
        "name",
        ["", "   ", "\t", "\n"],
        ids=["empty", "spaces", "tab", "newline"],
    )
    def test_blank_name_falls_back_to_the_default(
        self, client, path, greeting, route, name
    ):
        """`?name=` is present but useless, and should not greet the empty string."""
        response = client.get(path, query_string={"name": name})

        assert response.json["message"] == f"{greeting}, {DEFAULT_NAME}!"

    def test_surrounding_whitespace_is_stripped(self, client, path, greeting, route):
        response = client.get(path, query_string={"name": "  Brian  "})

        assert response.json["message"] == f"{greeting}, Brian!"

    def test_inner_whitespace_is_preserved(self, client, path, greeting, route):
        response = client.get(path, query_string={"name": "Ada Lovelace"})

        assert response.json["message"] == f"{greeting}, Ada Lovelace!"

    def test_name_at_the_length_cap_is_untouched(self, client, path, greeting, route):
        name = "a" * MAX_NAME_LENGTH

        response = client.get(path, query_string={"name": name})

        assert response.json["message"] == f"{greeting}, {name}!"

    def test_long_name_is_truncated_to_the_cap(self, client, path, greeting, route):
        response = client.get(path, query_string={"name": "a" * (MAX_NAME_LENGTH * 3)})

        assert response.json["message"] == f"{greeting}, {'a' * MAX_NAME_LENGTH}!"

    def test_name_is_stripped_before_it_is_truncated(
        self, client, path, greeting, route
    ):
        """Leading spaces must not eat into the budget of real characters."""
        name = "a" * MAX_NAME_LENGTH

        response = client.get(path, query_string={"name": f"    {name}    "})

        assert response.json["message"] == f"{greeting}, {name}!"

    def test_handles_non_ascii_names(self, client, path, greeting, route):
        response = client.get(path, query_string={"name": "Zoë"})

        assert response.json["message"] == f"{greeting}, Zoë!"

    def test_only_the_last_repeated_parameter_is_ignored(
        self, client, path, greeting, route
    ):
        """Flask's `args.get` takes the first value; pin that down."""
        response = client.get(f"{path}?name=First&name=Second")

        assert response.json["message"] == f"{greeting}, First!"

    def test_rejects_non_get_methods(self, client, path, greeting, route):
        """The routes are registered with `@app.get`, so anything else is 405."""
        assert client.post(path).status_code == 405


class TestHealth:
    def test_reports_ok(self, client):
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json == {"status": "ok"}

    def test_ignores_query_parameters(self, client):
        assert client.get("/health", query_string={"name": "Brian"}).json == {
            "status": "ok"
        }


class TestIndex:
    def test_advertises_the_service_and_its_routes(self, client):
        response = client.get("/")

        assert response.status_code == 200
        assert response.json["service"] == "ecs-fargate-demo"
        assert response.json["routes"] == [
            "/hello?name=",
            "/goodbye?name=",
            "/health",
        ]


class TestNotFound:
    def test_unknown_path_returns_404(self, client):
        assert client.get("/nope").status_code == 404

    def test_unknown_path_returns_json_not_html(self, client):
        """The error handler exists so a curl against a typo is still readable."""
        response = client.get("/nope")

        assert response.mimetype == "application/json"
        assert response.json["error"] == "not found"
        assert response.json["routes"] == ["/hello", "/goodbye", "/health"]

    def test_greeting_routes_are_not_prefixes(self, client):
        """/hello/Brian is a mistake, not a second way to pass a name."""
        assert client.get("/hello/Brian").status_code == 404

    def test_logs_a_warning_with_the_path(self, client, caplog):
        with caplog.at_level(logging.WARNING, logger="app"):
            client.get("/nope")

        record = caplog.records[0]
        assert record.levelname == "WARNING"
        assert record.event == "not_found"
        assert record.path == "/nope"


class TestStructuredLogging:
    """The routes log fields, not interpolated prose."""

    @pytest.fixture
    def records(self, client, caplog):
        def _get(path, **kwargs):
            caplog.clear()
            with caplog.at_level(logging.INFO, logger="app"):
                client.get(path, **kwargs)
            return caplog.records

        return _get

    @pytest.mark.parametrize(
        "path,event,route",
        [("/hello", "greeting", "hello"), ("/goodbye", "farewell", "goodbye")],
    )
    def test_greeting_routes_log_their_fields(self, records, path, event, route):
        record = records(path, query_string={"name": "Brian"})[0]

        assert record.event == event
        assert record.route == route
        assert record.greeted == "Brian"

    def test_the_logged_name_is_the_resolved_one(self, records):
        """Not the raw parameter -- the default, trimmed and capped value."""
        assert records("/hello")[0].greeted == DEFAULT_NAME
        assert records("/hello", query_string={"name": "  Brian "})[0].greeted == "Brian"
        assert (
            len(records("/hello", query_string={"name": "a" * 500})[0].greeted)
            == MAX_NAME_LENGTH
        )

    def test_health_is_not_logged(self, records):
        """The target group polls this every few seconds, forever."""
        assert records("/health") == []

    def test_a_request_id_is_always_attached(self, records):
        assert records("/hello")[0].request_id

    def test_the_alb_trace_header_is_used_as_the_request_id(self, records):
        trace = "Root=1-63441c4a-abcdef0123456789abcdef01"

        record = records("/hello", headers={"X-Amzn-Trace-Id": trace})[0]

        assert record.request_id == trace

    def test_each_request_gets_its_own_id_without_a_load_balancer(self, records):
        first = records("/hello")[0].request_id
        second = records("/hello")[0].request_id

        assert first != second

    def test_the_record_renders_as_one_json_line(self, records):
        rendered = JsonFormatter().format(records("/hello")[0])

        assert "\n" not in rendered
        payload = json.loads(rendered)
        assert payload["message"] == "greeting issued"
        assert payload["level"] == "INFO"
        assert payload["route"] == "hello"
        assert payload["greeted"] == DEFAULT_NAME
