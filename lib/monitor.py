"""Client library for publishing status updates to the pubsub monitor."""

import json
import time
import urllib.error
import urllib.request

# Timeout for all HTTP calls to pubsub (seconds).
HTTP_TIMEOUT = 10


class Monitor:
    """Publishes status blobs to the pubsub server under a monitor prefix."""

    def __init__(self, host="localhost", port=19103, token="", prefix="monitor"):
        self.base_url = f"http://{host}:{port}"
        self.token = token
        self.prefix = prefix
        self._last_error_log = 0  # rate-limit error logging

    def publish(self, path, name, status, value, weight=1, details=""):
        """Publish a status blob to pubsub.

        Args:
            path: Relative path under the monitor prefix (e.g. "mac/disk").
            name: Display label for the treemap node.
            status: Health status - "good", "warn", or "bad".
            value: Value string shown in center of treemap box.
            weight: Relative importance among siblings (must be > 0).
            details: Tooltip text shown on hover.

        Returns:
            Response dict from pubsub, or None if the publish failed.

        Raises:
            ValueError: If status or weight are invalid (programming errors).
        """
        if status not in ("good", "warn", "bad"):
            raise ValueError(f"status must be good/warn/bad, got {status!r}")
        if weight <= 0:
            raise ValueError(f"weight must be > 0, got {weight}")

        blob = {
            "weight": weight,
            "status": status,
            "name": name,
            "value": value,
            "details": details,
            "timestamp": time.time(),
        }

        full_path = f"{self.prefix}/{path}" if self.prefix else path
        url = f"{self.base_url}/put/{full_path}?token={self.token}"
        body = json.dumps(blob).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, OSError, ValueError) as e:
            self._log_error(f"publish {path}: {e}")
            return None

    def delete(self, path):
        """Delete a value from pubsub. Returns response dict or None."""
        full_path = f"{self.prefix}/{path}" if self.prefix else path
        url = f"{self.base_url}/del/{full_path}?token={self.token}"
        req = urllib.request.Request(url)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                return json.loads(resp.read())
        except (urllib.error.URLError, OSError, ValueError) as e:
            self._log_error(f"delete {path}: {e}")
            return None

    def _log_error(self, msg):
        """Log errors at most once per 60 seconds to avoid log spam."""
        now = time.time()
        if now - self._last_error_log > 60:
            print(f"  [pubsub] {msg}")
            self._last_error_log = now
