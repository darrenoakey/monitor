"""Integration tests for the monitor client library.

Tests against a running pubsub server on localhost:19103.
Tests against a running UI server on localhost:8090.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid

import pytest

from monitor import Monitor

TOKEN_PATH = os.path.expanduser("~/src/pubsub/data/token")


def read_token():
    with open(TOKEN_PATH) as f:
        return f.read().strip()


TOKEN = read_token()


def unique_path():
    """Generate a unique path to avoid test collisions."""
    return f"test/{uuid.uuid4().hex[:8]}"


def get_from_pubsub(path):
    """Read a value directly from pubsub."""
    url = f"http://localhost:19103/get/{path}?time=0&token={TOKEN}"
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


TEST_PREFIX = "testing"


@pytest.fixture
def mon():
    return Monitor(token=TOKEN, prefix=TEST_PREFIX)


class TestPublish:
    def test_publish_stores_blob(self, mon):
        path = unique_path()
        mon.publish(path, "Test Node", "good", "42%", weight=5, details="test details")

        result = get_from_pubsub(f"{TEST_PREFIX}/{path}")
        blob = result["value"]
        assert blob["name"] == "Test Node"
        assert blob["status"] == "good"
        assert blob["value"] == "42%"
        assert blob["weight"] == 5
        assert blob["details"] == "test details"
        assert isinstance(blob["timestamp"], float)

    def test_publish_returns_time(self, mon):
        path = unique_path()
        resp = mon.publish(path, "Node", "good", "ok")
        assert "time" in resp
        assert isinstance(resp["time"], int)

    def test_publish_default_weight(self, mon):
        path = unique_path()
        mon.publish(path, "Node", "warn", "80%")

        result = get_from_pubsub(f"{TEST_PREFIX}/{path}")
        blob = result["value"]
        assert blob["weight"] == 1

    def test_publish_warn_status(self, mon):
        path = unique_path()
        mon.publish(path, "Disk", "warn", "85%")

        result = get_from_pubsub(f"{TEST_PREFIX}/{path}")
        blob = result["value"]
        assert blob["status"] == "warn"

    def test_publish_bad_status(self, mon):
        path = unique_path()
        mon.publish(path, "CPU", "bad", "99%")

        result = get_from_pubsub(f"{TEST_PREFIX}/{path}")
        blob = result["value"]
        assert blob["status"] == "bad"

    def test_publish_timestamp_is_recent(self, mon):
        path = unique_path()
        before = time.time()
        mon.publish(path, "Node", "good", "ok")
        after = time.time()

        result = get_from_pubsub(f"{TEST_PREFIX}/{path}")
        blob = result["value"]
        assert before <= blob["timestamp"] <= after


class TestValidation:
    def test_invalid_status_raises(self, mon):
        with pytest.raises(ValueError, match="status must be"):
            mon.publish(unique_path(), "Node", "unknown", "val")

    def test_zero_weight_raises(self, mon):
        with pytest.raises(ValueError, match="weight must be"):
            mon.publish(unique_path(), "Node", "good", "val", weight=0)

    def test_negative_weight_raises(self, mon):
        with pytest.raises(ValueError, match="weight must be"):
            mon.publish(unique_path(), "Node", "good", "val", weight=-1)


class TestResilience:
    """Verify publish/delete never crash when pubsub is unreachable."""

    def test_publish_to_dead_server_returns_none(self):
        dead = Monitor(host="localhost", port=19199, token="fake")
        result = dead.publish("test/node", "Node", "good", "ok")
        assert result is None

    def test_delete_from_dead_server_returns_none(self):
        dead = Monitor(host="localhost", port=19199, token="fake")
        result = dead.delete("test/node")
        assert result is None


class TestDelete:
    def test_delete_clears_value(self, mon):
        path = unique_path()
        mon.publish(path, "Node", "good", "ok")
        mon.delete(path)

        result = get_from_pubsub(f"{TEST_PREFIX}/{path}")
        assert result.get("value") is None

    def test_delete_returns_time(self, mon):
        path = unique_path()
        mon.publish(path, "Node", "good", "ok")
        resp = mon.delete(path)
        assert "time" in resp


UI_BASE = "http://localhost:8090"


def fetch(path):
    with urllib.request.urlopen(f"{UI_BASE}{path}") as resp:
        return resp.status, resp.read().decode(), resp.headers


class TestUIServer:
    """Smoke tests for the UI server (must be running on port 8090)."""

    def test_index_returns_html(self):
        status, body, _ = fetch("/")
        assert status == 200
        assert "<!DOCTYPE html>" in body

    def test_static_tags_resolved(self):
        """No raw {{ static:... }} tags in served HTML."""
        _, body, _ = fetch("/")
        assert "{{ static:" not in body

    def test_token_injected(self):
        """Server injects pubsub token into meta tag."""
        _, body, _ = fetch("/")
        match = re.search(r'<meta name="pubsub-token" content="([^"]+)"', body)
        assert match, "pubsub-token meta tag missing or empty"
        assert len(match.group(1)) > 0

    def test_static_urls_have_hashes(self):
        """Static URLs contain ?v= content hashes."""
        _, body, _ = fetch("/")
        matches = re.findall(r'/static/\S+\?v=([a-f0-9]+)', body)
        assert len(matches) >= 2, f"Expected >=2 hashed static refs, got {matches}"
        for h in matches:
            assert len(h) == 12, f"Hash should be 12 hex chars, got {h}"

    def test_js_served(self):
        """monitor.js is served and contains expected code."""
        _, body, headers = fetch("/static/monitor.js?v=0")
        assert "function" in body
        assert headers["Content-Type"] == "application/javascript"

    def test_css_served(self):
        """style.css is served and contains expected styles."""
        _, body, headers = fetch("/static/style.css?v=0")
        assert "#viewport" in body
        assert headers["Content-Type"] == "text/css"

    def test_static_cache_headers(self):
        """Static files have immutable cache headers."""
        _, _, headers = fetch("/static/style.css?v=0")
        assert "immutable" in headers["Cache-Control"]

    def test_index_no_cache(self):
        """HTML is not cached (so new hashes are picked up)."""
        _, _, headers = fetch("/")
        assert "no-cache" in headers["Cache-Control"]

    def test_context_menu_element(self):
        """HTML contains the context-menu div."""
        _, body, _ = fetch("/")
        assert 'id="context-menu"' in body

    def test_path_traversal_blocked(self):
        """Cannot traverse out of static directory."""
        try:
            fetch("/static/../index.html")
            assert False, "Should have returned 403"
        except urllib.error.HTTPError as e:
            assert e.code == 403

    def test_missing_static_404(self):
        """Unknown static files return 404."""
        try:
            fetch("/static/nonexistent.js")
            assert False, "Should have returned 404"
        except urllib.error.HTTPError as e:
            assert e.code == 404

    def test_index_sets_client_cookie(self):
        """First visit sets a persistent client_id cookie."""
        req = urllib.request.Request(f"{UI_BASE}/")
        with urllib.request.urlopen(req) as resp:
            cookies = resp.headers.get_all("Set-Cookie")
        assert any("client_id=" in c for c in cookies)

    def test_prefs_roundtrip(self):
        """PUT prefs then GET them back."""
        # Get a client_id cookie first
        req = urllib.request.Request(f"{UI_BASE}/")
        with urllib.request.urlopen(req) as resp:
            cookie_header = resp.headers.get("Set-Cookie")
        cookie = cookie_header.split(";")[0]  # "client_id=..."

        # PUT prefs
        data = json.dumps({"hidden": ["a/b", "c/d"]}).encode()
        req = urllib.request.Request(
            f"{UI_BASE}/prefs", data=data, method="PUT",
            headers={"Content-Type": "application/json", "Cookie": cookie},
        )
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200

        # GET prefs back
        req = urllib.request.Request(
            f"{UI_BASE}/prefs", headers={"Cookie": cookie},
        )
        with urllib.request.urlopen(req) as resp:
            prefs = json.loads(resp.read())
        assert prefs["hidden"] == ["a/b", "c/d"]
