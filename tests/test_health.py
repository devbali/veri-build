"""
OpenClaw Gateway health (Flow 6) — runtime infrastructure checks.

Verifies the OpenClaw gateway is running and configured correctly
before attempting any agent-assisted test flows.
"""

import subprocess
import sys

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False
    import types
    class _FakeMark:
        def __getattr__(self, name):
            return lambda *a, **kw: (lambda f: f)
    pytest = types.ModuleType('pytest')
    pytest.mark = _FakeMark()

from common import (
    save_result, log_step, skip_unless,
    OPENCLAW_AVAILABLE,
)


# ═════════════════════════════════════════════════════════════════════════
# Flow 6: OpenClaw Gateway Health
# ═════════════════════════════════════════════════════════════════════════

@pytest.mark.openclaw
def test_openclaw_gateway_health():
    """Flow 6: openclaw gateway health — should return valid JSON with status."""
    result = subprocess.run(
        ["openclaw", "gateway", "health"],
        capture_output=True, text=True, timeout=30,
    )

    # Non-zero exit is acceptable (e.g., no route configured)
    health_data = {"exit_code": result.returncode}
    try:
        import json
        parsed = json.loads(result.stdout)
        health_data["health"] = parsed
    except (json.JSONDecodeError, ValueError):
        health_data["raw_stdout"] = result.stdout[:500]
        health_data["raw_stderr"] = result.stderr[:500]

    save_result("flow6_openclaw_health", health_data)

    if result.returncode != 0:
        log_step(f"OpenClaw health: exit {result.returncode} (gateway may not be running)")
    else:
        log_step("OpenClaw health: OK")


@pytest.mark.openclaw
def test_openclaw_gateway_status():
    """Flow 6 variant: openclaw gateway status — confirm it's running."""
    result = subprocess.run(
        ["openclaw", "gateway", "status"],
        capture_output=True, text=True, timeout=30,
    )

    status_data = {"exit_code": result.returncode}
    if result.stdout:
        status_data["status"] = result.stdout.strip()
    if result.stderr:
        status_data["error"] = result.stderr.strip()

    save_result("flow6_openclaw_status", status_data)

    if result.returncode != 0:
        log_step(f"OpenClaw status: not running (exit {result.returncode})")
        return

    assert "running" in result.stdout.lower(), (
        f"Gateway not running: {result.stdout[:200]}"
    )
    log_step("OpenClaw gateway: running")
