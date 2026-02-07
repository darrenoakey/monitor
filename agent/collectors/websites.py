"""Website health checker. Checks registered websites and services with ports."""

import json
import os
import ssl
import urllib.error
import urllib.request

# autogui state file location
AUTOGUI_STATE = os.path.expanduser("~/src/auto-gui/local/state.json")

# Timeout for HTTP checks
CONNECT_TIMEOUT = 10


def _load_targets():
    """Load website URLs from autogui state."""
    targets = []
    if not os.path.exists(AUTOGUI_STATE):
        return targets

    with open(AUTOGUI_STATE) as f:
        state = json.load(f)

    # Add registered websites
    for name, site in state.get("websites", {}).items():
        url = site.get("url", "")
        if url and site.get("visible", True):
            targets.append((name, url))

    # Add HTML services with ports (they serve web pages)
    for name, proc in state.get("processes", {}).items():
        port = proc.get("port")
        if port and proc.get("is_html") and proc.get("visible", True):
            targets.append((name, f"http://localhost:{port}"))

    return targets


# Create a context that doesn't verify certs (for local/self-signed services)
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def collect():
    """Return list of (path, name, status, value, weight, details) tuples."""
    targets = _load_targets()
    results = []

    for name, url in targets:
        key = name.lower().replace(" ", "-")
        try:
            # Try HEAD first, fall back to GET if 405
            req = urllib.request.Request(url, method="HEAD")
            try:
                with urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT, context=_ssl_ctx) as resp:
                    code = resp.status
            except urllib.error.HTTPError as e:
                if e.code == 405:
                    req = urllib.request.Request(url, method="GET")
                    with urllib.request.urlopen(req, timeout=CONNECT_TIMEOUT, context=_ssl_ctx) as resp:
                        code = resp.status
                else:
                    raise

            if code == 200:
                status = "good"
                value = "200"
            else:
                status = "warn"
                value = str(code)
            details = f"{url} -> {code}"
        except urllib.error.HTTPError as e:
            status = "bad" if e.code >= 500 else "warn"
            value = str(e.code)
            details = f"{url} -> {e.code}"
        except Exception as e:
            status = "bad"
            value = "down"
            err = str(e)[:60]
            details = f"{url} -> {err}"

        results.append((
            f"websites/{key}",
            name,
            status,
            value,
            1,
            details,
        ))
    return results
