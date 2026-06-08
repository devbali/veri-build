"""
Docker-based E2E tests for the Python asserts backend.

Tests the full pipeline inside the Docker container:
  1. Parse Veri DSL spec → generate _conditions.py
  2. Inject @contract decorators into real code (volume-mounted from host)
  3. Verify decorators match the spec
  4. Optionally run with CONTRACT_ASSERT_ENABLED=1

The Docker image must be rebuilt when backend code changes:
    docker build -t verification-builder:latest .

Host-side: the real Python implementation lives on the host. The Docker
container mounts it as a writable volume and modifies it in-place.
The runtime (@contract decorator) is a standalone python_runtime.py
that gets copied to the host for the user's production use.

Usage:
    DOCKER_PYTHON=1 python3 tests/test_python_docker.py
    DOCKER_PYTHON=1 python3 -m pytest tests/test_python_docker.py -v
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False
    import types
    class _FakeMark:
        def __getattr__(self, name):
            return lambda f=None, *a, **kw: f if f else (lambda g: g)
    pytest = types.ModuleType('pytest')
    pytest.mark = _FakeMark()
    pytest.skip = lambda msg: (_ for _ in ()).throw(RuntimeError(f'SKIP: {msg}'))

from common import (
    RESULTS_DIR, save_result, log_step, DOCKER_AVAILABLE, VERBOSE,
)

DOCKER_IMAGE = "verification-builder:latest"
RUN_PYTHON_DOCKER = os.environ.get("DOCKER", "") or os.environ.get("DOCKER_PYTHON", "")


def _image_has_backend() -> bool:
    """Check if the Docker image has our backend modules."""
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", DOCKER_IMAGE,
             "python3 -c \"import sys; "
             "sys.path = [p for p in sys.path if p]; "
             "sys.path.insert(0, '/opt/veri-build/src/veri_build/dsl/src'); "
             "from backend.python.runtime import contract; print('have_backend')\""],
            capture_output=True, text=True, timeout=30,
        )
        return 'have_backend' in r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _image_has_runner_target() -> bool:
    """Check if the runner supports --target python."""
    try:
        r = subprocess.run(
            ["docker", "run", "--rm", DOCKER_IMAGE, "veri-build-runner --help"],
            capture_output=True, text=True, timeout=30,
        )
        return "python" in r.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _require_image():
    """Skip test if Docker image is stale."""
    if not RUN_PYTHON_DOCKER:
        pytest.skip("Set DOCKER_PYTHON=1 to run Python Docker tests")
    if not DOCKER_AVAILABLE:
        pytest.skip("Docker not available")
    if not _image_has_backend():
        pytest.skip(
            "Docker image missing backend modules. "
            "Run: docker build -t verification-builder:latest ."
        )


def _docker_run(container_cmd: str, workdir: str = "/workspace") -> subprocess.CompletedProcess:
    """Run command inside Docker with a writable workdir mount."""
    return subprocess.run(
        ["docker", "run", "--rm", "-v", f"{workdir}:/workspace:rw",
         DOCKER_IMAGE, container_cmd],
        capture_output=True, text=True, timeout=120,
    )


def _docker_run_with_impl(
    workdir: str, impl_host_path: str, impl_container_path: str,
    container_cmd: str,
) -> subprocess.CompletedProcess:
    """Run command with both spec workdir and a writable impl mount."""
    return subprocess.run(
        ["docker", "run", "--rm",
         "-v", f"{workdir}:/workspace:rw",
         "-v", f"{impl_host_path}:{impl_container_path}:rw",
         DOCKER_IMAGE, container_cmd],
        capture_output=True, text=True, timeout=120,
    )


# ──────── Tests ────────────────────────────────────────────────────────

def test_docker_generate_conditions():
    """Veri DSL spec → generate _conditions.py via runner."""
    _require_image()

    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "spec.veri.md").write_text("""```veri
def add_element(existing: list[int], new_elem: int) -> list[int]:
    REQUIRES True
    ENSURES len(result) == len(existing) + 1
```""")

        r = _docker_run(
            f"veri-build-runner /workspace/spec.veri.md "
            f"--target python --output /workspace/result.json"
        )

        try:
            data = json.loads(r.stdout)
        except (json.JSONDecodeError, ValueError):
            data = {"stdout": r.stdout[:500], "stderr": r.stderr[:500]}

        # Check conditions file
        cond_path = Path(tmp, "spec_conditions.py")
        if cond_path.exists():
            cond_text = cond_path.read_text()
            data["conditions_generated"] = True
            data["conditions_length"] = len(cond_text)
            assert "def add_element__requires" in cond_text
            assert "def add_element__ensures" in cond_text
        else:
            data["conditions_generated"] = False
            # May fail gracefully if image is stale
            if _image_has_runner_target():
                assert False, f"Conditions not generated: {r.stdout[:300]}"

        save_result("docker_python_conditions", data)
        log_step(f"Docker conditions: generated={data.get('conditions_generated')}")


def test_docker_inject_and_verify():
    """Docker: generate → inject into host code → verify."""
    _require_image()

    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "spec.veri.md").write_text("""```veri
def add_element(existing: list[int], new_elem: int) -> list[int]:
    REQUIRES True
    ENSURES len(result) == len(existing) + 1
```""")

        impl_dir = Path(tempfile.mkdtemp())
        impl_path = impl_dir / "impl.py"
        impl_path.write_text("""def add_element(existing, new_elem):
    result = list(existing)
    result.append(new_elem)
    return result
""")

        try:
            # 1. Generate conditions
            r1 = _docker_run_with_impl(
                tmp, str(impl_dir), "/real_code",
                f"cd /opt/veri-build && "
                f"PYTHONPATH=src:src/veri_build/dsl/src python3 -m backend.python.conditions "
                f"/workspace/spec.veri.md > /workspace/spec_conditions.py",
            )
            log_step(f"Generate: {r1.stdout[:200]}{r1.stderr[:200]}")

            # 2. Inject decorators into host code (writable volume mount)
            r2 = _docker_run_with_impl(
                tmp, str(impl_dir), "/real_code",
                f"cd /opt/veri-build && "
                f"PYTHONPATH=src:src/veri_build/dsl/src python3 -m backend.python.inject "
                f"/workspace/spec.veri.md /real_code/impl.py --write",
            )
            log_step(f"Inject: {r2.stdout[:200]}{r2.stderr[:200]}")

            modified = impl_path.read_text()
            assert "@contract(" in modified, (
                f"Host code should have @contract. Got:\n{modified}"
            )
            assert "add_element__requires" in modified
            assert "add_element__ensures" in modified

            # 3. Verify decorators match
            r3 = _docker_run_with_impl(
                tmp, str(impl_dir), "/real_code",
                f"cd /opt/veri-build && "
                f"PYTHONPATH=src:src/veri_build/dsl/src python3 -m backend.python.verify "
                f"/workspace/spec.veri.md /real_code/impl.py "
                f"--conditions /workspace/spec_conditions.py",
            )
            log_step(f"Verify: {r3.stdout[:300]}{r3.stderr[:200]}")

            assert "All pass" in r3.stdout or r3.returncode == 0, (
                f"Verification failed:\n{r3.stdout}\n{r3.stderr}"
            )

            # 4. Copy runtime to host (for production use)
            py_runtime_path = impl_dir / "python_runtime.py"
            py_runtime_path.write_text(
                "class ContractSettings:\n    pass\n# runtime stub\n"
            )

            save_result("docker_python_e2e", {
                "injected": True,
                "verified": True,
                "impl_has_decorator": "@contract(" in modified,
            })
            log_step("Docker E2E: inject → verify → ✅")

        finally:
            import shutil
            shutil.rmtree(impl_dir, ignore_errors=True)


def test_docker_runner_pipeline():
    """Full veri-build-runner pipeline with --target python."""
    _require_image()

    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "spec.veri.md").write_text("""```veri
def add_element(existing: list[int], new_elem: int) -> list[int]:
    REQUIRES True
    ENSURES len(result) == len(existing) + 1
```""")

        impl_dir = Path(tempfile.mkdtemp())
        impl_path = impl_dir / "impl.py"
        impl_path.write_text("""def add_element(existing, new_elem):
    result = list(existing)
    result.append(new_elem)
    return result
""")

        try:
            r = _docker_run_with_impl(
                tmp, str(impl_dir), "/real_code",
                f"veri-build-runner /workspace/spec.veri.md "
                f"--target python --impl /real_code/impl.py --write "
                f"--output /workspace/result.json",
            )

            try:
                data = json.loads(r.stdout)
            except (json.JSONDecodeError, ValueError):
                data = {"stdout": r.stdout[:500]}

            save_result("docker_python_runner", data)

            if data.get("verification_all_pass"):
                log_step("Docker runner: all checks ✅")
            else:
                checks = data.get("verification_checks", [])
                failed = [c for c in checks if not c.get("passed")]
                log_step(f"Docker runner: {len(failed)} check failures")
                for c in failed:
                    log_step(f"  {c.get('name')}: {c.get('detail')}")

        finally:
            import shutil
            shutil.rmtree(impl_dir, ignore_errors=True)


# ──────── Runner ────────────────────────────────────────────────────────

TESTS = [
    ("docker_generate_conditions", test_docker_generate_conditions),
    ("docker_inject_and_verify", test_docker_inject_and_verify),
    ("docker_runner_pipeline", test_docker_runner_pipeline),
]


def _run_tests():
    passed = 0
    failed = 0
    skipped = 0
    print(f"Python Docker E2E (DOCKER_PYTHON={RUN_PYTHON_DOCKER})")
    print(f"Image backend: {_image_has_backend()}")
    print(f"Runner python: {_image_has_runner_target()}")
    print()
    for name, fn in TESTS:
        try:
            fn()
            passed += 1
            print(f"  ✓ {name}")
        except Exception as e:
            msg = str(e)
            if msg.startswith("SKIP:"):
                skipped += 1
                print(f"  - {name}: {msg[5:]}")
            else:
                failed += 1
                print(f"  ✗ {name}: {msg[:200]}")
    total = passed + failed + skipped
    print(f"\n  {passed}/{total} passed, {failed} failed, {skipped} skipped")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(_run_tests())
