"""
conftest.py — Shared pytest fixtures for all Veri DSL verification tests.

Available to any test file in this directory tree.
"""

import os
import pytest

from common import DOCKER_AVAILABLE, OPENCLAW_AVAILABLE, RUN_DOCKER, RUN_AGENT


# ── Environment-based skip markers ──────────────────────────────────────

def pytest_configure(config):
    """Register custom markers so pytest doesn't warn about them."""
    config.addinivalue_line("markers", "docker: requires DOCKER=1 env var")
    config.addinivalue_line("markers", "agent(name): requires DOCKER_AGENT=<name> env var")
    config.addinivalue_line("markers", "openclaw: requires `which openclaw`")


@pytest.fixture
def project_root():
    """Return the veri-build project root."""
    from pathlib import Path
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def fixtures_dir(project_root):
    """Return the integration test fixtures directory."""
    return project_root / "tests" / "integration" / "fixtures"


@pytest.fixture
def results_dir(project_root):
    """Return the integration test results directory (creates if needed)."""
    d = project_root / "tests" / "integration" / "results"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Fixtures that skip unless the right env is set ─────────────────────

@pytest.fixture
def docker_required():
    """Skip test unless DOCKER=1 and Docker is available."""
    if not RUN_DOCKER:
        pytest.skip("Set DOCKER=1 to run Docker tests")
    if not DOCKER_AVAILABLE:
        pytest.skip("Docker not available")


@pytest.fixture
def agent_claude():
    """Skip test unless DOCKER_AGENT=claude."""
    if RUN_AGENT != "claude":
        pytest.skip("Set DOCKER_AGENT=claude to run agent tests")


@pytest.fixture
def agent_openclaw():
    """Skip test unless DOCKER_AGENT=openclaw."""
    if RUN_AGENT != "openclaw":
        pytest.skip("Set DOCKER_AGENT=openclaw to run agent tests")


@pytest.fixture
def openclaw_required():
    """Skip test unless `which openclaw` succeeds."""
    if not OPENCLAW_AVAILABLE:
        pytest.skip("openclaw CLI not found on PATH")


# ── Marker-based skip resolution ───────────────────────────────────────

def pytest_runtest_setup(item):
    """Allow markers like @pytest.mark.docker to auto-skip."""
    if item.get_closest_marker("docker"):
        if not RUN_DOCKER:
            pytest.skip("Set DOCKER=1")
        if not DOCKER_AVAILABLE:
            pytest.skip("Docker unavailable")

    marker = item.get_closest_marker("agent")
    if marker:
        expected = marker.args[0] if marker.args else None
        if not expected:
            pytest.skip("agent marker needs a name, e.g. @pytest.mark.agent('claude')")
        if expected == "claude" and RUN_AGENT != "claude":
            pytest.skip(f"Set DOCKER_AGENT={expected}")
        if expected == "openclaw" and RUN_AGENT != "openclaw":
            pytest.skip(f"Set DOCKER_AGENT={expected}")

    if item.get_closest_marker("openclaw"):
        if not OPENCLAW_AVAILABLE:
            pytest.skip("openclaw CLI not found")
