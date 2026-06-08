"""
common.py — Shared test infrastructure for Veri DSL verification tests.

All test files import from here instead of duplicating path setup,
result saving, fixture extraction, and environment gating.
"""

import json
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional


# ═════════════════════════════════════════════════════════════════════════
# Paths
# ═════════════════════════════════════════════════════════════════════════

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROJECT = _PROJECT_ROOT / "src"
sys.path.insert(0, str(PROJECT))

DSL_SRC = _PROJECT_ROOT / "src" / "veri_build" / "dsl" / "src"
sys.path.insert(0, str(DSL_SRC))

FIXTURES = _PROJECT_ROOT / "tests" / "integration" / "fixtures"
RESULTS_DIR = _PROJECT_ROOT / "tests" / "integration" / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)


# ═════════════════════════════════════════════════════════════════════════
# Environment gates
# ═════════════════════════════════════════════════════════════════════════

DOCKER_AVAILABLE = os.system("docker info >/dev/null 2>&1") == 0
OPENCLAW_AVAILABLE = os.system("which openclaw >/dev/null 2>&1") == 0
RUN_DOCKER = os.environ.get("DOCKER", "")
RUN_AGENT = os.environ.get("DOCKER_AGENT", "").lower()
VERBOSE = '-v' in sys.argv or '--verbose' in sys.argv or bool(os.environ.get("VERBOSE"))


# ═════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════

def save_result(name: str, data: Dict[str, Any]) -> Path:
    """Write a JSON result file to tests/integration/results/."""
    path = RESULTS_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str))
    return path


def log_step(msg: str):
    """Print a step header if verbose mode is on."""
    if VERBOSE:
        print(f"\n    ── {msg} ──")


def skip_unless(condition: bool, msg: str):
    """Skip a test with a message — works with or without pytest.

    Raises RuntimeError(SKIP: ...) outside pytest, or pytest.skip() inside.
    """
    if condition:
        return False
    try:
        import pytest
        pytest.skip(msg)
    except ImportError:
        raise RuntimeError(f'SKIP: {msg}')


def extract_veri_blocks(md_text: str) -> List[str]:
    """Extract ```veri ... ``` blocks from a .veri.md file."""
    return re.findall(r'```veri\n(.*?)```', md_text, re.DOTALL)


def pipeline_config(target: str, **overrides) -> object:
    """Create a CompilerConfig with sensible test defaults.

    Usage:
        config = pipeline_config("fstar")
        config = pipeline_config("dafny", use_docker=True, agent="claude")
    """
    from veri_build.pipeline import CompilerConfig
    defaults = {
        "target": target,
        "use_docker": False,
        "verify": False,
        "agent": None,
        "timeout_seconds": 300,
    }
    defaults.update(overrides)
    return CompilerConfig(**defaults)
