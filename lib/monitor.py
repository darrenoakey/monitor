"""Client library for publishing status updates to the pubsub monitor."""

import json
import time
import urllib.request


class Monitor:
    """Publishes status blobs to the pubsub server under a monitor prefix."""

    def __init__(self, host="localhost", port=19103, token="", prefix="monitor"):
        self.base_url = f"http://{host}:{port}"
        self.token = token
        self.prefix = prefix

    def publish(self, path, name, status, value, weight=1, details=""):
        """Publish a status blob to pubsub.

        Args:
            path: Relative path under the monitor prefix (e.g. "mac/disk").
            name: Display label for the treemap node.
            status: Health status - "good", "warn", or "bad".
            value: Value string shown in center of treemap box.
            weight: Relative importance among siblings (must be > 0).
            details: Tooltip text shown on hover.
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
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())

    def delete(self, path):
        """Delete a value from pubsub."""
        full_path = f"{self.prefix}/{path}" if self.prefix else path
        url = f"{self.base_url}/del/{full_path}?token={self.token}"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
