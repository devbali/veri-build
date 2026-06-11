# Adding a Compilation Backend

The Veri Build pipeline compiles Veri DSL specs through a chain:

```
.veri.md → F* interface → LLM agent writes let defs → fstar verify → backend extract
```

The **backend** is the last step — it takes verified F* code and produces the output
artifact (C, OCaml, Wasm, etc.). Each backend is a self-contained plugin.

## How it works

A backend does three things:

1. **Provides agent rules** — extra instructions for the LLM agent about what
   F* subset to write (e.g., "no `*` operator" for C, no restrictions for OCaml).
2. **Extracts output code** — runs the compiler that turns F* into the target
   language (e.g., `krml` for C, `fstar --codegen OCaml` for OCaml).
3. **Reports what it produced** — returns the output file(s) path.

The generic pipeline handles everything else: parsing Veri DSL, generating the
F* interface, running the LLM agent, verifying with fstar, and retrying on
failure.

## Adding a new backend

Create a new file in `src/veri_build/backend/` and register it in `__init__.py`.

### Example: F* → WebAssembly

```python
# src/veri_build/backend/fstar_wasm.py
from backend.base import Backend

class FStarWasmBackend(Backend):
    name = "fstar-wasm"               # short identifier
    description = "F* → Wasm via fstar --codegen wasm"
    target_patterns = ["f-star-wasm"]  # TARGET line in .veri.md
    language = "Wasm"

    def agent_extra_rules(self) -> str:
        # Tell the agent what F* subset the Wasm backend supports.
        # Return "" if no extra restrictions.
        return (
            "WebAssembly extraction rules:\n"
            "- No FStar.Seq operations — use fixed-size buffers\n"
            "- All functions must be non-recursive\n"
        )

    def verify_extraction(self, module_path, output_dir):
        # Run the actual compiler
        import subprocess
        cmd = [
            "fstar.exe", "--codegen", "wasm",
            "--include", "/opt/fstar/lib/fstar/ulib",
            "--output_dir", str(output_dir),
            str(module_path),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if proc.returncode == 0:
            return True, "fstar --codegen wasm succeeded"
        return False, proc.stderr[-500:]

    def self_check_command(self) -> str:
        # Shell command for the agent's self-check step
        return ""
```

Then register it in `backend/__init__.py`:

```python
from backend.fstar_wasm import FStarWasmBackend
register(FStarWasmBackend())
```

### Required methods

| Method | Returns | Purpose |
|---|---|---|
| `agent_extra_rules()` | str | Lines appended to agent prompt ("" if none) |
| `verify_extraction(fst_path, output_dir)` | `(bool, str)` | Run the compiler, return pass/fail + message |

### Optional methods

| Method | Default | Purpose |
|---|---|---|
| `dsl_language()` | Derived from name | Which DSL printer to use ('fstar', 'dafny', 'python') |
| `output_suffix()` | `""` | Output file extension (e.g., '.c', '.ml') |
| `self_check_command()` | `""` | Shell command for agent self-check step |

### Lifecycle

```
Agent writes F* let defs
       │
       ▼
fstar.exe verifies .fst (shared — all F* backends)
       │
       ▼
Backend.verify_extraction()  ← you implement this
       │
       ▼
Output files (.c, .ml, .wasm, ...)
```

## Existing backends

| Backend | ID | TARGET | Output | Compiler |
|---|---|---|---|---|
| F* → C | `fstar-c` | `fstar-c` | `.c` | krml |
| F* → OCaml | `fstar-ocaml` | `fstar-ocaml` | `.ml` | `fstar --codegen OCaml` |
| F* → Wasm | `fstar-wasm` | `fstar-wasm` | `.wasm` | krml `-wasm` |
| Dafny → Java | `dafny-java` | `dafny-java` | `.java` | `dafny translate java` |
| Dafny → JS | `dafny-js` | `dafny-js` | `.js` | `dafny translate js` |
| Dafny → Python | `dafny-python` | `dafny-python` | `.py` | `dafny translate py` |
| Dafny → Rust | `dafny-rust` | `dafny-rust` | `.rs` | `dafny translate rs` |
| Python | `python-assert` | `python-assert` | `.py` | `@contract` decorators |

**Dafny runtime dependency**: The generated Java/JS/Python code depends on
the Dafny runtime library (`DafnyRuntime.jar` for Java, `dafny.js` for JS,
`dafny.py` for Python). These are included in the Dafny installation at
`dafny/DafnyRuntime.*`. When compiling the generated code, add the Dafny
runtime to your classpath / import path. The `dafny translate` command does
*not* bundle the runtime automatically — you must distribute it alongside
your compiled output.
