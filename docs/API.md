# Veri DSL Pipeline — APIs

The veri-build pipeline has four APIs. The LLM's primary workflow is
**verify+convert**: write F*/Dafny, verify it, convert to Veri DSL for the user.

| API | Direction | Purpose | Primary? |
|-----|-----------|---------|----------|
| **Verify+Convert** | F*/Dafny **→** Veri DSL (verified) | LLM writes target code, verifies, converts to Veri DSL | ✅ Yes |
| **Convert** | F* or Dafny **→** Veri DSL (raw) | Straight conversion, no verification | ❌ Backup |
| **Lint** | Veri DSL → verify | Validate Veri DSL spec compiles to well-formed target | ❌ Backup |
| **Compile** | Veri DSL **→** F*/Dafny → verify → C/Rust | Full pipeline, agent fills TODOs, converts back | ⚠️ When user edits Veri DSL |

> **Veri DSL-only constraint:** `.veri.md` files shown to users MUST always be in
> Veri DSL. Any ````veri```` block containing raw target-language keywords
> (`val`, `let`, `module`, `open`, `function`, `method`, `datatype`) is rejected.

---

## API 0: Verify+Convert (Primary — target → verified Veri DSL)

**Purpose:** Take F* or Dafny code, verify it with the target verifier,
and convert the result to user-facing Veri DSL. This is the main API the LLM uses.

**Input:** F* or Dafny code (string)
**Output:** `VerifyConvertResult` with verified flag and Veri DSL string

```python
from veri_build.pipeline import verify_and_convert

result = verify_and_convert(fstar_code, target='fstar', module_name='Module')
if result.verified:
    print(result.veri)  # Veri DSL spec for the user's .veri.md
else:
    print(result.error)  # fix the F*/Dafny and retry
```

**VerifyConvertResult fields:**
- `verified: bool` — verifier accepted the code
- `veri: str | None` — Veri DSL converted from verified code
- `target_code: str | None` — original target code (echoed back)
- `error: str | None` — error message (verification failure, tool not found, etc.)
- `stdout / stderr: str` — raw verifier output for debugging

---

## API 1: Convert (target → Veri DSL)

**Purpose:** Convert target-language code (F* or Dafny) back to Veri DSL DSL syntax.
Used to read verified implementations as user-facing Veri DSL. This is the REVERSE
direction — taking what the verifier/agent produced and showing it to the user.

### F*F* → Veri DSL

```python
from veri_build.pipeline import convert_fstar_to_veri

veri = convert_fstar_to_veri("""
val add: x:int -> y:int -> Pure int
  (requires True)
  (ensures (fun r -> r = x + y))
""")
```

**What it handles:**
- `val f: params -> effect ret` → `def f(params) -> ret: REQUIRES ... ENSURES ...`
- `open Module` → `import Module`
- `type X = Y` → `type X = Y`
- `let rec f(...): ret = body` → `def f(...) -> ret: return ...`
- Multi-line requires/ensures clauses

### DafnyF* → Veri DSL

(Work in progress — uses `dafny_parser` → `veri_printer` internally)
The pipeline calls this automatically during compile; direct API coming soon.

---

## API 2: Linter (`lint`)

**Purpose:** Validate a `.veri.md` file. Checks:
1. All ````veri```` blocks are valid **Veri DSL** (rejects raw F*, Dafny)
2. Veri DSL parses through the Veri DSL parser
3. Generated target code verifies with target verifier (fstar.exe or dafny)
4. When target='fstar', enforces Low* subset for C extraction

**Input:** Path to `.veri.md`, target language
**Output:** `LintResult` (passed, errors, warnings, diagnostics)

```python
from veri_build.pipeline import lint

# Lint for F* → C pipeline (checks Low* compliance)
result = lint("examples/binary_search.veri.md", target='fstar')

# Lint for Dafny → Rust pipeline
result = lint("examples/circular_buffer.veri.md", target='dafny')

if result.passed:
    print(f"✅ Lint passed!")
else:
    for e in result.errors:
        print(f"  Error: {e}")
```

**Veri DSL-only enforcement:** The linter uses keyword heuristics + Veri DSL parser to
distinguish Veri DSL from raw target language. Blocks containing `val`, `let`,
`assume`, `function`, `method`, `datatype` without Veri DSL equivalents are rejected.

**Low* enforcement:** When target='fstar', the linter checks for Low* violations
(no ST effect, no heap refs, restricted effects) to ensure C extractability.

---

## API 3: Compiler (`compile_veri`)

**Purpose:** End-to-end pipeline. Converts Veri DSL to target language, launches a
sub-agent inside a Docker sandbox to fill TODOs, verifies the result, and
optionally compiles to the output language.

**Pipeline steps:**
1. Read `.veri.md` → parse Veri DSL into AST
2. Generate target-language interface + implementation stubs
3. Launch sub-agent in Docker sandbox with credentials mounted
4. Agent fills TODOs, verifies with target verifier
5. Compile to output language (C via KaRaMeL, Rust via Dafny backend)

**Input:** Path to `.veri.md`, CompilerConfig
**Output:** `CompileResult` (success, module_name, interface_path, impl_path, output_path, verification_passed)

```python
from veri_build.pipeline import compile_veri, CompilerConfig

# F* → C (via Low* / KaRaMeL)
config = CompilerConfig(
    target='fstar',          # verification language
    agent='claude',          # 'claude' or 'openclaw'
    timeout_seconds=600,
    use_docker=True,         # run in isolated Docker sandbox
)
result = compile_veri("examples/sorted_list.veri.md", config)
if result.success and result.verification_passed:
    print(f"✅ Module: {result.module_name}")
    print(f"   .fsti: {result.interface_path}")
    print(f"   .fst:  {result.impl_path}")
    if result.output_path:
        print(f"   .c:    {result.output_path}")

# Dafny → Rust
config = CompilerConfig(
    target='dafny',
    agent='claude',
)
result = compile_veri("examples/circular_buffer.veri.md", config)
```

### Single-invocation Docker pipeline

When `use_docker=True` and `compile_veri()` is called, everything runs
inside a single Docker container invocation. One script does it all:

```
┌─────────────────────────────────────────────────────────────────────┐
│  docker run verification-builder veri-build-runner spec.veri.md    │
│                                                                     │
│  Inside container (one Python script):                              │
│    1. Parse Veri DSL → generate target interface (.fsti / .dfy header)  │
│    2. Run verifier (fstar.exe / dafny verify) on interface         │
│    3. Convert verified interface back to Veri DSL                       │
│    4. If --agent set: launch sub-agent to fill TODOs               │
│       (Claude Code or OpenClaw with mounted credentials)           │
│    5. Verify agent's filled implementation                         │
│    6. Output results as JSON                                       │
│                                                                     │
│  User never sees raw F* or Dafny — only Veri DSL.                       │
└─────────────────────────────────────────────────────────────────────┘
```

The `veri-build-runner` command (symlink to
`scripts/compile_parent_subagent_runner.py`) is installed in the Docker
image at `/usr/local/bin/veri-build-runner`. It handles
all steps in one process.

## Sub-agent contract

The sub-agent runs inside Docker with:
- **Claude Code:** `~/.claude/.credentials.json` mounted as `/root/.claude/.credentials.json`
- **OpenClaw agent:** `~/.openclaw/identity/` and `~/.openclaw/.env` mounted

The prompt sent to the agent follows this strict workflow contract:

```
Step 1 ── Produce ONLY incomplete target-language interface
          F*: .fsti (types + val signatures only, NO let-bindings,
               NO admit(), NO stubs)
          Dafny: .dfy header (datatypes + function/method sigs, NO bodies)

Step 2 ── Run the verifier on the interface
          F*: fstar.exe on .fsti (no admits, pure interface check)
          Dafny: dafny verify on .dfy

Step 3 ── Convert verified target code BACK to Veri DSL
          F*: fsti_parser → veri_printer
          Dafny: dafny_parser → veri_printer

          The Veri DSL spec is what gets shown to the user.
          NEVER show raw target language to the user.

Step 4 ── Iterate: if the interface doesn't verify or the Veri DSL looks
          wrong, fix the target interface and repeat from Step 2.
```

**HARD RULES:**
- The user ONLY ever sees Veri DSL. Target languages (F*, Dafny) are internal.
- Generated interfaces must be INCOMPLETE (no implementations).
- Always verify before converting back to Veri DSL.
- If Veri DSL conversion looks incorrect, fix the interface, don't patch the Veri DSL.

When the sub-agent is filling TODOs (not just generating an interface),
the same rules apply: produce verified target code, then convert back to
Veri DSL for the user. The Veri DSL `.veri.md` is the single source of truth.

---

## Target language mapping

| Veri DSL | F* (for C via Low*) | Dafny (for Rust) |
|-----|---------------------|------------------|
| `class X: f: T` | `type x = { f: t }` | `datatype X = X(f: T)` |
| `type X = Y` | `type x = y` | `type X = Y` |
| `type X = Y WHERE p` | `type x = x:y{p}` | `type X = x: T \| P` |
| `def f(p:T) -> R: return ...` | `let f (p:T) : R = ...` | `function method f(p: T): R { ... }` |
| `def f(p:T) -> R: REQUIRES... ENSURES...` | `val f: p:T -> Pure R (requires...) (ensures...)` | `function method f(p: T): R requires... ensures...` |
| `match x: case A: ...` | `match x with \| A -> ...` | `match x { case A => ... }` |
| `list[T]` | `list t` | `seq<T>` |
| `option[T]` | `option t` | `Option<T>` |
| `and` / `or` / `not` | `/\` / `\/` / `~` | `&&` / `\|\|` / `!` |
| `len(x)` | `List.Tot.length x` | `\|x\|` |
| `result` in ensures | `result` (F* built-in) | `result` (Dafny keyword) |

---

## File conventions

| File | Content | Lifecycle |
|------|---------|-----------|
| `.veri.md` | Veri DSL source | Human-authored, never modified by tools |
| `.fsti` | F* interface (generated) | Transient, regenerated each run |
| `.fst` | F* implementation with admit() stubs | Agent fills this |
| `.dfy` | Dafny source (generated from Veri DSL) | Agent fills TODOs |
| `.c` | C output (via KaRaMeL) | Compiled from verified F* |
| `.rs` | Rust output (via Dafny) | Compiled from verified Dafny |
| `.veri` | Standalone Veri DSL source (no markdown) | Alternative to .veri.md |

---

## CLI usage

```bash
# Lint a .veri.md (F* target, checks Low* for C)
python3 -m veri_build.pipeline lint path/to/file.veri.md --target fstar

# Lint for Dafny target
python3 -m veri_build.pipeline lint path/to/file.veri.md --target dafny

# Compile with Claude Code in Docker sandbox (F* → C)
python3 -m veri_build.pipeline compile path/to/file.veri.md --target fstar -o build/

# Compile with OpenClaw agent (Dafny → Rust)
python3 -m veri_build.pipeline compile path/to/file.veri.md --target dafny --agent openclaw -o build/

# Compile locally (no Docker sandbox)
python3 -m veri_build.pipeline compile path/to/file.veri.md --target fstar --no-docker -o build/

# Convert F* to Veri DSL
python3 -m veri_build.pipeline convert path/to/fstar_code.fst
```

---

## End-to-End Workflow

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────┐
│ .veri.md    │────▶│ compile()        │────▶│ Docker       │
│ (Veri DSL spec)  │     │                  │     │ sandbox      │
└─────────────┘     │ 1. Parse Veri DSL     │     │              │
                    │ 2. Gen target    │     │ Claude/      │
                    │    interface     │     │ OpenClaw     │
                    │ 3. Launch agent ─┼────▶│ agent fills  │
                    │    in Docker     │     │ TODOs in     │
                    │ 4. Verify        │     │ F*/Dafny     │
                    │ 5. Compile       │     │              │
                    └───────┬──────────┘     └──────────────┘
                            │
                    ┌───────▼──────────┐
                    │ Output           │
                    │                  │
                    │ F* → C (KaRaMeL) │
                    │ Dafny → Rust     │
                    │                  │
                    │ .c / .rs         │
                    │ (VERIFIED! ✓)    │
                    └──────────────────┘
```

### Integration targets

| Veri DSL → Target → Output | Tooling | When to use |
|----------------------|---------|-------------|
| Veri DSL → F* → C | KaRaMeL (`krml`) | Need zero-overhead C for embedded systems, WASM |
| Veri DSL → Dafny → Rust | Dafny Rust backend | Need verified Rust with Dafny's type system |

### What the orchestrator (parent agent) does

1. **Write Veri DSL spec** in `.veri.md` (always Veri DSL, linter verifies)
2. **Run compile_veri** → launches agent in Docker, gets verified result
3. **Get output .c or .rs** — verified, ready for integration

The `.veri.md` (Veri DSL spec) and `.c`/`.rs` (verified output) are the user-facing artifacts.
Everything else (`.fsti`, `.dfy`, `.fst`) is intermediate.

### Key principles

- **Veri DSL-only:** Users write `.veri.md` in Veri DSL only. Raw F*/Dafny in ````veri```` blocks is rejected by the linter
- **Sandboxed agent:** The sub-agent runs in Docker with credentials mounted, no host filesystem access
- **Low* for C:** When target='fstar', the linter enforces Low* subset for KaRaMeL extractability
- **Multi-target:** Same Veri DSL spec compiles to F*→C or Dafny→Rust
- **Idempotent:** Generated files are transient; `.veri.md` is the source of truth
