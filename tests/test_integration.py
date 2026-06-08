#!/usr/bin/env python3
"""
Integration tests for the Veri DSL verification pipeline — COMPAT REDIRECT.

This file re-exports all parametrized backend tests from test_backend_generic.py
and the standalone tests from test_python.py, test_completeness.py, etc.

Test architecture (scales to 20+ backends):
  tests/backends.py                  ← Backend registry (add one entry per backend)
  tests/test_backend_generic.py      ← Parametrized tests over all registered backends
  tests/test_python.py               ← Runtime library tests (@contract behavior)
  tests/test_completeness.py         ← Cross-backend DSL completeness (flow 7)
  tests/test_scenario.py             ← End-to-end pipeline scenario
  tests/test_health.py               ← OpenClaw gateway health (flow 6)

Run:
  python3 -m pytest tests/ -v                           # All tests
  python3 -m pytest tests/test_backend_generic.py -v    # All backends, generic tests
  python3 -m pytest tests/test_backend_generic.py -k "fstar"  # Single backend
  python3 -m pytest tests/test_python.py -v             # Python runtime only
  python3 tests/                                        # Without pytest
"""

import warnings
warnings.warn(
    "test_integration.py is deprecated. Use tests/test_backend_generic.py "
    "for parametrized backend tests, or tests/test_*.py for specific test areas.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export all test functions from the modular files
from test_backend_generic import *   # noqa: F401, F403
from test_python import *            # noqa: F401, F403
from test_completeness import *      # noqa: F401, F403
from test_scenario import *          # noqa: F401, F403
from test_health import *            # noqa: F401, F403
