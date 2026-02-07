"""Integration tests for the monitor client library.

Tests against a running pubsub server on localhost:19103.
"""

import json
import os
import time
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


@pytest.fixture
def mon():
    return Monitor(token=TOKEN)


class TestPublish:
    def test_publish_stores_blob(self, mon):
        path = unique_path()
        mon.publish(path, "Test Node", "good", "42%", weight=5, details="test details")

        result = get_from_pubsub(f"monitor/{path}")
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

        result = get_from_pubsub(f"monitor/{path}")
        blob = result["value"]
        assert blob["weight"] == 1

    def test_publish_warn_status(self, mon):
        path = unique_path()
        mon.publish(path, "Disk", "warn", "85%")

        result = get_from_pubsub(f"monitor/{path}")
        blob = result["value"]
        assert blob["status"] == "warn"

    def test_publish_bad_status(self, mon):
        path = unique_path()
        mon.publish(path, "CPU", "bad", "99%")

        result = get_from_pubsub(f"monitor/{path}")
        blob = result["value"]
        assert blob["status"] == "bad"

    def test_publish_timestamp_is_recent(self, mon):
        path = unique_path()
        before = time.time()
        mon.publish(path, "Node", "good", "ok")
        after = time.time()

        result = get_from_pubsub(f"monitor/{path}")
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


class TestDelete:
    def test_delete_clears_value(self, mon):
        path = unique_path()
        mon.publish(path, "Node", "good", "ok")
        mon.delete(path)

        result = get_from_pubsub(f"monitor/{path}")
        assert result.get("value") is None

    def test_delete_returns_time(self, mon):
        path = unique_path()
        mon.publish(path, "Node", "good", "ok")
        resp = mon.delete(path)
        assert "time" in resp
