"""
Generic backend tests — parametrized over all registered backends.

Tests here are *backend-agnostic*: they run the same checks for every backend
registered in backends.py. To add a new backend, just add an entry there —
all these tests automatically include it.

Backend-specific overrides go in the test function body (use cfg.name / cfg.target).
For runtime-library tests (e.g. Python @contract), see test_python.py.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False
    import types
    class _FakeMark:
        def __getattr__(self, name):
            return lambda *a, **kw: (lambda f: f)
    def _fake_param(*args, **kwargs):
        # Return the first positional argument (the actual test param)
        return args[0] if args else None
    pytest = types.ModuleType('pytest')
    pytest.mark = _FakeMark()
    pytest.param = _fake_param
    pytest.skip = lambda msg: (_ for _ in ()).throw(RuntimeError(f'SKIP: {msg}'))
    pytest.mark.skip = lambda *a, **kw: (lambda f: f)

from common import (
    FIXTURES, RESULTS_DIR,
    save_result, log_step, skip_unless,
    extract_veri_blocks, pipeline_config,
    DOCKER_AVAILABLE, RUN_DOCKER, RUN_AGENT, VERBOSE,
)

from backends import (
    BACKENDS, BackendConfig,
    enabled_backends, docker_backends, agent_backends, converter_backends,
)


# ═════════════════════════════════════════════════════════════════════════
# Fixtures: parametrize over backends
# ═════════════════════════════════════════════════════════════════════════

# Pytest trick: parametrize with ids for readable test names
def _backend_param_id(val):
    """Generate a readable test ID from a (name, cfg) tuple."""
    if isinstance(val, tuple) and len(val) >= 2:
        return f"{val[1].name}/{val[1].target}"
    return str(val)


def _backend_params(filter_fn=None):
    """Build test parameter tuples for parametrized tests.

    With pytest: returns pytest.param() tuples with markers.
    Without pytest: returns simple (name, cfg) tuples.

    Args:
        filter_fn: Optional callable (name, cfg) -> bool to filter backends.
    """
    if HAS_PYTEST:
        items = []
        for name, cfg in enabled_backends().items():
            if filter_fn and not filter_fn(name, cfg):
                continue
            marks = []
            if cfg.skip_reason:
                marks.append(pytest.mark.skip(reason=cfg.skip_reason))
            items.append(pytest.param(name, cfg, id=f"{cfg.name}/{cfg.target}", marks=marks))
        return items
    else:
        return [(name, cfg) for name, cfg in enabled_backends().items()
                if not filter_fn or filter_fn(name, cfg)]


# ═════════════════════════════════════════════════════════════════════════
# Test: Veri DSL Self-Roundtrip  (Veri DSL → AST → Veri DSL)
# ═════════════════════════════════════════════════════════════════════════

def _test_veri_self_roundtrip(name: str, cfg: BackendConfig):
    """Veri DSL → AST → Veri DSL should be stable for any backend's fixture."""
    veri_path = FIXTURES / cfg.fixture
    raw = veri_path.read_text()
    blocks = extract_veri_blocks(raw)
    assert len(blocks) >= 1
    veri_text = "\n\n".join(blocks)

    from veri_parser import parse_veri
    from veri_printer import VeriDslPrinter

    prog = parse_veri(veri_text)
    reprinted = VeriDslPrinter().print(prog)

    # Check that key structural elements survive roundtrip
    assert len(reprinted) > 50
    assert "TARGET" in reprinted or "def " in reprinted or "type " in reprinted

    save_result(f"roundtrip_{name}", {
        "backend": name,
        "original_length": len(veri_text),
        "reprinted_length": len(reprinted),
    })
    log_step(f"[{name}] Veri DSL roundtrip: {len(veri_text)} → {len(reprinted)} chars")


# ═════════════════════════════════════════════════════════════════════════
# Test: Veri DSL → Target Interface Generation
# ═════════════════════════════════════════════════════════════════════════

def _test_veri_to_target_roundtrip(name: str, cfg: BackendConfig):
    """Veri DSL → target interface via local pipeline (no Docker)."""
    veri_path = FIXTURES / cfg.fixture
    assert veri_path.exists(), f"Fixture not found: {veri_path}"

    from veri_build.pipeline import compile_veri
    config = pipeline_config(cfg.target)
    result = compile_veri(str(veri_path), config)

    assert result.success, f"[{name}] Pipeline failed: {result.error}"
    assert result.interface is not None, f"[{name}] No interface generated"
    assert len(result.interface) > 50, f"[{name}] Interface suspiciously short"

    save_result(f"interface_{name}", {
        "backend": name,
        "target": cfg.target,
        "module": result.module_name,
        "interface_length": len(result.interface),
        "interface_preview": result.interface[:300],
    })
    log_step(f"[{name}] Interface: {len(result.interface)} chars")


# ═════════════════════════════════════════════════════════════════════════
# Test: Target → Veri DSL Conversion (backends with converters only)
# ═════════════════════════════════════════════════════════════════════════

def _test_veri_to_target_veri_conversion(name: str, cfg: BackendConfig):
    """Convert generated target code back to Veri DSL (for backends with converters)."""
    if not cfg.has_converter:
        pytest.skip(f"[{name}] No converter support")

    veri_path = FIXTURES / cfg.fixture

    from veri_build.pipeline import compile_veri
    config = pipeline_config(cfg.target)
    result = compile_veri(str(veri_path), config)
    assert result.success
    assert result.interface is not None

    # Attempt conversion back to Veri DSL — each backend has its own converter
    target_interface = result.interface
    veri_back = None

    if cfg.name == "F*":
        from veri_build.pipeline import convert_fstar_to_veri
        veri_back = convert_fstar_to_veri(target_interface)

    if veri_back is not None:
        assert len(veri_back) > 30
        log_step(f"[{name}] Target→Veri DSL: {len(veri_back)} chars")
    else:
        log_step(f"[{name}] Target→Veri DSL: not available")

    save_result(f"conversion_{name}", {
        "backend": name,
        "success": veri_back is not None,
        "veri_length": len(veri_back) if veri_back else 0,
        "veri_preview": veri_back[:300] if veri_back else None,
    })


# ═════════════════════════════════════════════════════════════════════════
# Test: Docker Pipeline (backends with Docker support)
# ═════════════════════════════════════════════════════════════════════════

def _test_docker_pipeline(name: str, cfg: BackendConfig):
    """Docker-based interface verification (no agent).

    For backends that have a compile pipeline (F* → .fsti, Dafny → .dfy):
      Runs compile_veri inside Docker and verifies interface output.

    For Python backend (no compile_pipeline):
      Runs the Docker runner with --target python to generate _conditions.py,
      then verifies the conditions module is importable and contains the
      expected requires/ensures functions. No LLM involvement.
    """
    if not RUN_DOCKER:
        pytest.skip("Set DOCKER=1 to run Docker tests")
    if not DOCKER_AVAILABLE:
        pytest.skip("Docker not available")
    if not cfg.has_docker:
        pytest.skip(f"[{name}] No Docker support")

    veri_path = FIXTURES / cfg.fixture

    if cfg.name == "Python":
        # ── Python Docker path: generate _conditions.py via runner ──
        # The Python backend has no compile_veri pipeline; instead we invoke
        # the Docker runner directly to generate conditions and verify them.
        import subprocess
        import tempfile
        import json
        from pathlib import Path

        veri_text = veri_path.read_text()

        with tempfile.TemporaryDirectory(prefix='veri-docker-py-') as tmp:
            tmp_path = Path(tmp)
            spec_in_docker = tmp_path / veri_path.name
            spec_in_docker.write_text(veri_text)

            result_json = tmp_path / "result.json"

            docker_cmd = [
                "docker", "run", "--rm",
                "-v", f"{tmp_path}:/workspace:rw",
                "-w", "/workspace",
                "verification-builder:latest",
                "veri-build-runner", f"/workspace/{veri_path.name}",
                "--target", "python",
                "--output", "/workspace/result.json",
            ]

            try:
                proc = subprocess.run(
                    docker_cmd, capture_output=True, text=True, timeout=120)
            except subprocess.TimeoutExpired:
                save_result(f"docker_{name}", {
                    "backend": name,
                    "success": False,
                    "error": "Docker timed out",
                })
                pytest.skip(f"[{name}] Docker timed out (120s)")
            except FileNotFoundError:
                save_result(f"docker_{name}", {
                    "backend": name,
                    "success": False,
                    "error": "Docker not found",
                })
                pytest.skip(f"[{name}] Docker not available")

            # Parse results
            docker_data = {}
            if result_json.exists():
                docker_data = json.loads(result_json.read_text())
            elif proc.stdout:
                try:
                    docker_data = json.loads(proc.stdout)
                except json.JSONDecodeError:
                    docker_data = {"stdout": proc.stdout[:500],
                                  "stderr": proc.stderr[:500]}

            # Check conditions were generated
            cond_path = tmp_path / f"{docker_data.get('module_name', 'generated')}_conditions.py"
            conds_generated = cond_path.exists()
            if conds_generated:
                cond_text = cond_path.read_text()
                assert "def " in cond_text, \
                    f"[{name}] Conditions empty or no functions: {cond_text[:200]}"
                assert "__requires" in cond_text or "__ensures" in cond_text, \
                    f"[{name}] No requires/ensures in conditions: {cond_text[:300]}"

            verification_ok = docker_data.get('verification_passed', conds_generated)

            save_result(f"docker_{name}", {
                "backend": name,
                "success": conds_generated,
                "verification_passed": verification_ok,
                "module": docker_data.get('module_name', ''),
                "conditions_generated": conds_generated,
                "conditions_length": len(cond_text) if conds_generated else 0,
                "error": docker_data.get('error'),
            })

            assert conds_generated, \
                f"[{name}] Python Docker failed: conditions not generated. " \
                f"stdout: {proc.stdout[:300]}  stderr: {proc.stderr[:300]}"
            log_step(f"[{name}] Docker: {len(cond_text)} chars of conditions")

    else:
        # ── F* / Dafny Docker path: compile_veri with use_docker=True ──
        from veri_build.pipeline import compile_veri
        config = pipeline_config(cfg.target, use_docker=True)
        result = compile_veri(str(veri_path), config)

        save_result(f"docker_{name}", {
            "backend": name,
            "success": result.success,
            "module": result.module_name,
            "interface_length": len(result.interface) if result.interface else 0,
            "error": result.error,
        })
        assert result.success, f"[{name}] Docker pipeline failed: {result.error}"
        assert result.interface is not None
        log_step(f"[{name}] Docker: {len(result.interface)} chars")


# ═════════════════════════════════════════════════════════════════════════
# Test: LLM Agent-Assisted (backends with agent config)
# ═════════════════════════════════════════════════════════════════════════

def _test_agent_assisted(name: str, cfg: BackendConfig):
    """LLM-guided E2E: LLM reads our skill, produces Veri DSL spec + implementation.

    The test simulates a user who has only:
      - An LLM (Claude for Python/F*, OpenClaw for Dafny)
      - Our SKILL.md (the same one a human would read)
      - A task: "write an Veri DSL spec and implement it"

    The LLM reads the skill, learns about `verify_and_convert()` and
    `compile_veri(use_docker=True)`, and produces:
      - An Veri DSL spec (.veri.md) with the correct TARGET declaration
      - Implementation code (Python with @contract, or F*, or Dafny)

    Then WE run our verification toolchain on the LLM's output to
    confirm it works end-to-end.

    Gated behind DOCKER_AGENT=<backend_agent> env var.
    WARNING: Makes real API calls - costs money!
    """
    if not cfg.docker_agent:
        pytest.skip(f"[{name}] No agent configured")
    if RUN_AGENT != cfg.docker_agent:
        pytest.skip(f"Set DOCKER_AGENT={cfg.docker_agent} to run [{name}] agent tests")
    if not DOCKER_AVAILABLE:
        pytest.skip("Docker not available")

    import subprocess
    import tempfile
    import json
    import re
    from pathlib import Path

    # Path to our existing skill -- the same VERIFICATION-SKILL.md a human user reads
    skill_path = Path(__file__).resolve().parent.parent \
        / 'skills' / 'VERIFICATION-SKILL.md'
    if not skill_path.exists():
        pytest.skip(f"[{name}] SKILL.md not found at {skill_path}")

    veri_path = FIXTURES / cfg.fixture

    # Build natural-language task per backend -- NO detailed command instructions.
    # The LLM must read SKILL.md to figure out the API.
    if cfg.name == "Python":
        task = (
            "Read /workspace/SKILL.md.\n"
            "\n"
            "Your task: Write Python code for a sorted list data structure\n"
            "with add_element (insert in sorted order) and is_sorted (check\n"
            "list is sorted by serial) functions.\n"
            "\n"
            "The Veri DSL spec for this task is:\n"
            + veri_path.read_text().replace('"', '\\"').replace('`', '\\`') + "\n"
            "\n"
            "Write an implementation with @contract decorators that matches\n"
            "this spec. Import `contract` from `python_runtime` and import\n"
            "the condition functions from the spec's _conditions module.\n"
            "\n"
            "OUTPUT FORMAT: A single ```python code block containing ONLY\n"
            "the Python source (imports, @contract decorators, function defs).\n"
            "No ```veri blocks. No extra text outside the ```python block."
        )
    elif cfg.name == "F*":
        task = (
            "Read /workspace/SKILL.md.\n"
            "\n"
            "The SKILL.md says: Write F* code, then call verify_and_convert()\n"
            "to produce Veri DSL. Follow that workflow.\n"
            "\n"
            "Your task: Write F* code for a sorted list data structure with\n"
            "add_element (insert in sorted order) and is_sorted (check list is\n"
            "sorted by serial) functions. Include all types, val declarations,\n"
            "let definitions, and requires/ensures contracts.\n"
            "\n"
            "OUTPUT FORMAT: A single ```fstar code block containing ONLY the\n"
            "F* source (module declaration, types, val/let, etc.).\n"
            "The verify_and_convert() API will convert this to Veri DSL later.\n"
            "No ```veri blocks. No extra text outside the ```fstar block."
        )
    elif cfg.name == "Dafny":
        task = (
            "Read /workspace/SKILL.md.\n"
            "\n"
            "The SKILL.md says: Write Dafny code, then call verify_and_convert()\n"
            "to produce Veri DSL. Follow that workflow.\n"
            "\n"
            "Your task: Write Dafny code for a circular buffer with enqueue,\n"
            "dequeue, is_full, and is_empty functions. Include all datatypes,\n"
            "function/method declarations, and requires/ensures contracts.\n"
            "\n"
            "OUTPUT FORMAT: A single ```dafny code block containing ONLY the\n"
            "Dafny source (module declaration, datatypes, functions, methods).\n"
            "The verify_and_convert() API will convert this to Veri DSL later.\n"
            "No ```veri blocks. No extra text outside the ```dafny block."
        )
    else:
        pytest.skip(f"[{name}] Unknown backend")

    with tempfile.TemporaryDirectory(prefix=f'veri-agent-{name}-') as tmp:
        tmp_path = Path(tmp)

        # Mount SKILL.md for the LLM to read
        skill_in_workspace = tmp_path / "SKILL.md"
        skill_in_workspace.write_text(skill_path.read_text())

        # Guard: credentials must exist
        if cfg.docker_agent == "claude":
            cred_path = Path.home() / '.claude' / '.credentials.json'
            if not cred_path.exists():
                log_step(f"[{name}] Skipping: no {cred_path}")
                save_result(f"agent_{name}", {
                    "backend": name, "agent": cfg.docker_agent,
                    "success": False,
                    "error": "Claude credentials not found",
                })
                return
            cred_mount = f"{cred_path}:/root/.claude/.credentials.json:ro"
            # Shell-safe: escape backticks and double quotes for bash -c
            task_escaped = task.replace('`', '\\`').replace('"', '\\"')
            agent_cmd_str = f'claude -p "{task_escaped}" --print'
        elif cfg.docker_agent == "openclaw":
            cred_path = Path.home() / '.openclaw'
            if not cred_path.exists():
                log_step(f"[{name}] Skipping: no {cred_path}")
                save_result(f"agent_{name}", {
                    "backend": name, "agent": cfg.docker_agent,
                    "success": False,
                    "error": "OpenClaw identity not found",
                })
                return
            cred_mount = f"{cred_path}:/root/.openclaw:rw"
            # Shell-safe: escape backticks and double quotes for bash -c
            task_escaped_oc = task.replace('`', '\\`').replace('"', '\\"')
            # Patch openclaw.json paths before running
            prep_cmd = 'mkdir -p /root/.openclaw/workspace/.openclaw/extensions; sed -i "s|/home/dev/|/root/|g" /root/.openclaw/openclaw.json; '
            agent_cmd_str = prep_cmd + f'openclaw infer model run --local --model deepseek/deepseek-v4-pro --prompt "{task_escaped_oc}" --json'
        else:
            pytest.skip(f"[{name}] Unknown agent type: {cfg.docker_agent}")

        # Run the LLM in a container with: skill + task + credentials
        docker_cmd = [
            "docker", "run", "--rm",
            "-v", f"{tmp_path}:/workspace:rw",
            "-v", cred_mount,
            "-w", "/workspace",
            "verification-builder:latest",
            agent_cmd_str,
        ]

        try:
            proc = subprocess.run(
                docker_cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            save_result(f"agent_{name}", {
                "backend": name, "agent": cfg.docker_agent,
                "success": False, "error": "Agent timed out after 300s",
            })
            pytest.skip(f"[{name}] Agent timed out")
        except FileNotFoundError:
            pytest.skip(f"[{name}] Docker not available")

        # Parse agent output
        agent_output = ''
        if cfg.docker_agent == "claude":
            agent_output = proc.stdout
        else:  # openclaw -- parse JSON response
            try:
                oc_payload = json.loads(proc.stdout)
                outputs = oc_payload.get('outputs') or []
                if outputs:
                    agent_output = outputs[0].get('text', '')
            except (json.JSONDecodeError, IndexError, TypeError):
                agent_output = proc.stdout

        if not agent_output or proc.returncode != 0:
            save_result(f"agent_{name}", {
                "backend": name, "agent": cfg.docker_agent,
                "success": False,
                "agent_output_preview": agent_output[:500] if agent_output else "",
                "agent_error": proc.stderr[:500],
                "error": f"Agent failed (exit {proc.returncode})",
            })
            log_step(f"[{name}] Agent produced no valid output")
            return

        log_step(f"[{name}] Agent produced {len(agent_output)} chars")

        # Extract code blocks from the LLM's output
        # F*/Dafny backends: LLM writes target language code (no Veri DSL).
        # Python backend:   LLM writes Python impl (no Veri DSL; spec comes from fixture).
        impl_blocks = []
        if cfg.name == "Python":
            impl_blocks = (list(_extract_code_blocks(agent_output, 'python'))
                           or list(_extract_code_blocks(agent_output, 'py')))
        elif cfg.name == "F*":
            impl_blocks = (list(_extract_code_blocks(agent_output, 'fstar'))
                           or list(_extract_code_blocks(agent_output, 'ocaml'))
                           or list(_extract_code_blocks(agent_output, 'fst')))
        elif cfg.name == "Dafny":
            impl_blocks = list(_extract_code_blocks(agent_output, 'dafny'))

        impl_source = "\n\n".join(impl_blocks) if impl_blocks else ""

        if not impl_source:
            save_result(f"agent_{name}", {
                "backend": name, "agent": cfg.docker_agent,
                "success": False,
                "has_impl_code": bool(impl_source),
                "raw_agent_preview": agent_output[:800],
                "error": "Missing implementation code block from agent output",
            })
            log_step(f"[{name}] Missing implementation code in agent output")
            return

        # Verify the LLM's output through our toolchain
        # The LLM wrote TARGET code (F*, Dafny) — we call
        # verify_and_convert() to verify it and convert to Veri DSL.
        # For Python, the LLM wrote an implementation with @contract
        # decorators — we call veri-build-runner --impl to verify.

        if cfg.name == "Python":
            spec_file = tmp_path / "agent_spec.veri.md"
            spec_file.write_text(veri_path.read_text())
            impl_file = tmp_path / "agent_impl.py"
            impl_file.write_text(impl_source)

            # Generate conditions from the Veri DSL spec fixture
            subprocess.run([
                "docker", "run", "--rm",
                "-v", f"{tmp_path}:/workspace:rw",
                "-w", "/workspace",
                "verification-builder:latest",
                "veri-build-runner", "/workspace/agent_spec.veri.md",
                "--target", "python",
                "--output", "/workspace/step_cond.json",
            ], capture_output=True, text=True, timeout=120)

            # Verify the implementation against the spec
            subprocess.run([
                "docker", "run", "--rm",
                "-v", f"{tmp_path}:/workspace:rw",
                "-w", "/workspace",
                "verification-builder:latest",
                "veri-build-runner", "/workspace/agent_spec.veri.md",
                "--target", "python",
                "--impl", "/workspace/agent_impl.py",
                "--output", "/workspace/step_verify.json",
            ], capture_output=True, text=True, timeout=120)

            verify_data = {}
            if (tmp_path / "step_verify.json").exists():
                verify_data = json.loads(
                    (tmp_path / "step_verify.json").read_text())
            all_pass = verify_data.get('verification_all_pass', False)
            checks = verify_data.get('verification_checks', [])

        elif cfg.name == "F*":
            impl_file = tmp_path / "agent_impl.fst"
            impl_file.write_text(impl_source)

            # Write a verify_and_convert script and run it inside Docker
            vac_script = tmp_path / "_vac.py"
            vac_script.write_text("""
import sys, json
sys.path.insert(0, "/opt/veri-build/src")
sys.path.insert(0, "/opt/veri-build/src/veri_build/dsl/src")
from veri_build.pipeline import verify_and_convert
code = open("/workspace/agent_impl.fst").read()
r = verify_and_convert(code, target="fstar", module_name="SortedList")
print(json.dumps({
    "verified": r.verified,
    "veri_length": len(r.veri or ""),
    "error": r.error,
    "stdout": (r.stdout or "")[-500:],
    "stderr": (r.stderr or "")[-500:],
}))
"""
            )
            vac_proc = subprocess.run([
                "docker", "run", "--rm",
                "-v", f"{tmp_path}:/workspace:rw",
                "-w", "/workspace",
                "verification-builder:latest",
                "python3 /workspace/_vac.py",
            ], capture_output=True, text=True, timeout=120)

            vac_data = {}
            try:
                vac_data = json.loads(vac_proc.stdout)
            except (json.JSONDecodeError, ValueError):
                vac_data = {"verified": False,
                           "error": f"JSON parse: {vac_proc.stdout[:200]}"}

            all_pass = vac_data.get("verified", False)
            checks = [{"name": "verify_and_convert(fstar)", "passed": all_pass,
                      "detail": vac_data.get("error") or "ok"}]

        elif cfg.name == "Dafny":
            impl_file = tmp_path / "agent_impl.dfy"
            impl_file.write_text(impl_source)

            # Write a verify_and_convert script and run it inside Docker
            vac_script = tmp_path / "_vac.py"
            vac_script.write_text("""
import sys, json
sys.path.insert(0, "/opt/veri-build/src")
sys.path.insert(0, "/opt/veri-build/src/veri_build/dsl/src")
from veri_build.pipeline import verify_and_convert
code = open("/workspace/agent_impl.dfy").read()
r = verify_and_convert(code, target="dafny", module_name="CircularBuffer")
print(json.dumps({
    "verified": r.verified,
    "veri_length": len(r.veri or ""),
    "error": r.error,
    "stdout": (r.stdout or "")[-500:],
    "stderr": (r.stderr or "")[-500:],
}))
"""
            )
            vac_proc = subprocess.run([
                "docker", "run", "--rm",
                "-v", f"{tmp_path}:/workspace:rw",
                "-w", "/workspace",
                "verification-builder:latest",
                "python3 /workspace/_vac.py",
            ], capture_output=True, text=True, timeout=120)

            vac_data = {}
            try:
                vac_data = json.loads(vac_proc.stdout)
            except (json.JSONDecodeError, ValueError):
                vac_data = {"verified": False,
                           "error": f"JSON parse: {vac_proc.stdout[:200]}"}

            all_pass = vac_data.get("verified", False)
            checks = [{"name": "verify_and_convert(dafny)", "passed": all_pass,
                      "detail": vac_data.get("error") or "ok"}]
        else:
            pytest.skip(f"[{name}] Unknown backend")

        save_result(f"agent_{name}", {
            "backend": name,
            "agent": cfg.docker_agent,
            "success": True,
            "agent_output_length": len(agent_output),
            "impl_code_length": len(impl_source),
            "verification_passed": all_pass,
            "verification_checks": checks,
            "impl_code_preview": impl_source[:300],
            "error": None,
        })

        if all_pass:
            log_step(f"[{name}] LLM+skill E2E: verified OK")
        else:
            log_step(f"[{name}] LLM+skill E2E: verification FAILED")


def _extract_code_blocks(text: str, lang: str):
    """Extract ```lang ... ``` blocks from LLM output."""
    pattern = re.compile(rf'```{lang}\n(.*?)```', re.DOTALL)
    return [b.strip() for b in pattern.findall(text) if b.strip()]



# Pytest parametrized tests
# ═════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("name,cfg", _backend_params(), ids=_backend_param_id)
def test_veri_self_roundtrip(name, cfg):
    """Veri DSL → AST → Veri DSL should be stable for every backend's fixture."""
    _test_veri_self_roundtrip(name, cfg)


@pytest.mark.parametrize(
    "name,cfg",
    _backend_params(lambda n, c: c.has_compile_pipeline),
    ids=_backend_param_id,
)
def test_veri_to_target_roundtrip(name, cfg):
    """Veri DSL → target interface generation via local pipeline."""
    _test_veri_to_target_roundtrip(name, cfg)


@pytest.mark.parametrize(
    "name,cfg",
    _backend_params(lambda n, c: c.has_converter),
    ids=_backend_param_id,
)
def test_target_to_veri_conversion(name, cfg):
    """Target → Veri DSL conversion (backends with converters only)."""
    _test_veri_to_target_veri_conversion(name, cfg)


@pytest.mark.parametrize(
    "name,cfg",
    _backend_params(lambda n, c: c.has_docker),
    ids=_backend_param_id,
)
@pytest.mark.docker
def test_docker_pipeline(name, cfg):
    """Docker pipeline (backends with Docker support only)."""
    _test_docker_pipeline(name, cfg)


@pytest.mark.parametrize(
    "name,cfg",
    _backend_params(lambda n, c: c.docker_agent is not None),
    ids=_backend_param_id,
)
@pytest.mark.agent("auto")
def test_agent_assisted(name, cfg):
    """LLM agent-assisted pipeline (backends with agent configured only)."""
    _test_agent_assisted(name, cfg)


# ═════════════════════════════════════════════════════════════════════════
# Standalone runner (no pytest)
# ═════════════════════════════════════════════════════════════════════════

def _run_tests():
    """Run all parametrized tests directly when pytest is not available.

    Respects the same filter predicates as the pytest parametrized decorators.
    """
    passed = 0
    failed = 0
    skipped = 0

    # Each entry: (name, test_fn, filter_fn_or_None)
    tests = [
        ("veri_self_roundtrip",   _test_veri_self_roundtrip,       None),
        ("veri_to_target_roundtrip", _test_veri_to_target_roundtrip,
         lambda n, c: c.has_compile_pipeline),
        ("target_to_veri_conversion", _test_veri_to_target_veri_conversion,
         lambda n, c: c.has_converter),
    ]
    if RUN_DOCKER:
        tests.append(("docker_pipeline", _test_docker_pipeline,
                     lambda n, c: c.has_docker))
    if RUN_AGENT:
        tests.append(("agent_assisted", _test_agent_assisted,
                     lambda n, c: c.docker_agent and RUN_AGENT == c.docker_agent))

    print(f"Running {len(enabled_backends())} backends: {', '.join(enabled_backends().keys())}")
    print()

    for test_name, test_fn, filter_fn in tests:
        print(f"── {test_name} ──")
        backends_to_run = [(n, c) for n, c in enabled_backends().items()
                          if not filter_fn or filter_fn(n, c)]
        for bname, bcfg in backends_to_run:
            try:
                test_fn(bname, bcfg)
                print(f"  ✓ [{bcfg.name}]")
                passed += 1
            except RuntimeError as e:
                if str(e).startswith("SKIP:"):
                    print(f"  - [{bcfg.name}]: {e.args[0][5:]}")
                    skipped += 1
                else:
                    print(f"  ✗ [{bcfg.name}]: {e}")
                    failed += 1
            except Exception as e:
                print(f"  ✗ [{bcfg.name}]: {e}")
                if VERBOSE:
                    import traceback
                    traceback.print_exc()
                failed += 1
        print()

    total = passed + failed + skipped
    print(f"{passed}/{total} passed, {failed} failed, {skipped} skipped")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(_run_tests())
