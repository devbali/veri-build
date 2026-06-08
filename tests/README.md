# Veri DSL Verification — Test Coverage

Tests are organized around a **backend registry** that scales to any number of backends.
Adding a new backend = one entry in [`backends.py`](backends.py), and all parametrized
tests in [`test_backend_generic.py`](test_backend_generic.py) auto-include it.

Common infrastructure lives in [`common.py`](common.py).

## Coverage Matrix

| Test Type \ Backend | **F\*** (→ C) | **Dafny** (→ Rust) | **Python** (asserts) | **Next backend...** |
|---|---|---|---|---|
| **Veri DSL self-roundtrip** (ASTF* → Veri DSL) | ✅ generic | ✅ generic | ✅ generic | ✅ auto |
| **Interface generation** (`compile_veri`) | ✅ generic | ✅ generic | *skipped (no compile_veri)* | ✅ auto |
| **Target → Veri DSL conversion** | ✅ generic | ❌ not impl | ❌ not impl | ✅ if supported |
| **Docker (no agent)** | ✅ generic | ✅ generic | ✅ generic (runner → _conditions.py) | ✅ if `has_docker` |
| **LLM-guided (Claude Code)** | ✅ generic | — | ✅ generic (agent writes impl → inject → verify) | ✅ if `docker_agent` |
| **LLM-guided (OpenClaw)** | — | ✅ generic | — | ✅ if `docker_agent` |
| **Runtime library** (e.g. `@contract`) | — | — | [`test_python.py`](test_python.py) | ✅ if `has_runtime_lib` |
| **DSL completeness** (AST parity) | [`test_completeness.py`](test_completeness.py) | same | same | same |
| **E2E scenario** (full roundtrip) | [`test_scenario.py`](test_scenario.py) | same | *(future)* | same |
| **OpenClaw health** | [`test_health.py`](test_health.py) | same | same | same |

**Generic** = parametrized in `test_backend_generic.py` — runs for every backend
that has the relevant capability flag set to `True` in `backends.py`.

## Test Naming Convention

```
tests/
├── README.md                        # ← this file
├── backends.py                      # Backend registry (add one entry per backend!)
├── common.py                        # Shared: paths, helpers, result saving
├── conftest.py                      # Pytest fixtures (docker/agent markers)
├── test_backend_generic.py          # Parametrized tests over all backends
├── test_python.py                   # Python runtime tests (@contract behavior)
├── test_spec.py                     # Spec parsing (standalone)
├── test_completeness.py             # Cross-backend DSL completeness (flow 7)
├── test_scenario.py                 # End-to-end pipeline scenario
├── test_health.py                   # OpenClaw gateway health (flow 6)
├── test_integration.py              # Compat shim (re-exports from all above)
└── integration/
    ├── README.md                    # Fixture & results documentation
    ├── fixtures/                    # .veri.md, .fsti, .dfy test inputs
    └── results/                     # JSON results from test runs
```

## Adding a New Backend

To add a new backend (say, Coq or Lean):

1. **Add the backend to the pipeline** in `src/veri_build/dsl/src/backend/`
2. **Register it in [`tests/backends.py`](backends.py):**

    ```python
    "coq": BackendConfig(
        name="Coq",
        target="coq",
        fixture="my_coq_spec.veri.md",
        has_compile_pipeline=True,
        has_docker=True,
        docker_agent=None,       # no LLM agent yet
        has_converter=False,     # no Coq→Veri DSL parser yet
        has_parser=False,
        has_runtime_lib=False,
    ),
    ```

3. **Add a fixture** in `tests/integration/fixtures/my_coq_spec.veri.md`
4. **Done.** All generic tests automatically include the new backend.

## Running Tests

```bash
# All tests (local only, no Docker)
cd ~/project/verification/veri-build
python3 -m pytest tests/ -v

# All backends, generic interface tests
python3 -m pytest tests/test_backend_generic.py -v

# Single backend (pytest -k matches the test ID: "F*/fstar")
python3 -m pytest tests/test_backend_generic.py -k "Fstar" -v
python3 -m pytest tests/test_backend_generic.py -k "Dafny" -v
python3 -m pytest tests/test_backend_generic.py -k "Python" -v

# Python runtime tests (@contract behavior)
python3 -m pytest tests/test_python.py -v

# Python Docker pipeline (requires DOCKER=1)
DOCKER=1 python3 -m pytest tests/test_backend_generic.py -k "Python.*docker" -v

# Python LLM-guided (requires DOCKER_AGENT=claude + Claude API creds)
DOCKER_AGENT=claude python3 -m pytest tests/test_backend_generic.py -k "Python.*agent" -v

# With Docker (interface verification, no agent) — all backends
DOCKER=1 python3 -m pytest tests/test_backend_generic.py -k "docker" -v

# With real agent execution (expensive — API calls!) — all backends
DOCKER_AGENT=claude  python3 -m pytest tests/test_backend_generic.py -k "agent" -v
DOCKER_AGENT=openclaw python3 -m pytest tests/test_backend_generic.py -k "agent" -v

# Dry run (no pytest)
python3 tests/test_completeness.py
python3 tests/test_scenario.py
python3 tests/test_python.py
python3 tests/test_backend_generic.py
```

## Common Infrastructure

All test scripts import from [`tests/common.py`](common.py):

| Symbol | Purpose |
|---|---|
| `PROJECT` | Root of `src/` for `sys.path` injection |
| `FIXTURES` | Path to `tests/integration/fixtures/` |
| `RESULTS_DIR` | Path to `tests/integration/results/` |
| `save_result(name, data)` | Write JSON result to `results/` |
| `extract_veri_blocks(md_text)` | Extract ` ```veri ` blocks from markdown |
| `log_step(msg)` | Verbose step logging |
| `skip_unless(condition, msg)` | Pytest-compatible skip |
| `DOCKER_AVAILABLE` | `bool`: `docker info` works |
| `OPENCLAW_AVAILABLE` | `bool`: `which openclaw` works |
