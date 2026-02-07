"""Agent configuration. Reads from environment variables with sensible defaults."""

import os
import socket


def machine_name():
    """Short machine name for the pubsub path."""
    name = os.environ.get("MONITOR_MACHINE")
    if name:
        return name
    # Use hostname, lowercased, stripped of .local
    h = socket.gethostname().lower().replace(".local", "")
    # Simplify common patterns
    for suffix in ("-mbp", "-macbook-pro", "-imac"):
        if h.endswith(suffix):
            h = h[: -len(suffix)]
    return h.replace(" ", "-").replace("'", "").replace("'", "")


def pubsub_host():
    return os.environ.get("MONITOR_PUBSUB_HOST", "localhost")


def pubsub_port():
    return int(os.environ.get("MONITOR_PUBSUB_PORT", "19103"))


def pubsub_token():
    """Read token from env or from the pubsub data/token file."""
    token = os.environ.get("MONITOR_PUBSUB_TOKEN", "")
    if token:
        return token
    # Try reading from local pubsub installation
    token_path = os.path.expanduser("~/src/pubsub/data/token")
    if os.path.exists(token_path):
        with open(token_path) as f:
            return f.read().strip()
    return ""
