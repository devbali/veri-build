---
name: veri-dsl-verification
description: Write F*/Dafny/Python specs, verify with fstar.exe/dafny/runtime assertions, and convert to user-facing Veri DSL. Use when the task involves formal verification, writing .veri.f.md/.veri.dfy.md files, running target verifiers, contract specifications, or compiling verified code to C (via Low*/KaRaMeL), Rust (via Dafny), or Python (runtime @contract). Triggers on: "verify", "Veri DSL", "veri.md", "F*", "Dafny", "Python", "formally verified", "contract spec", "Low*", "target: string".
---

# Veri DSL Verification

## Core loop

Work in F*, Dafny, or Python. Write F*/Dafny in a temp `.veri.f.md` / `.veri.dfy.md`
file, or write Python directly in the spec. Then call `verify_and_convert()` to
check and convert to user-facing Veri DSL.

```
Write F*/Dafny/Python  →  verify_and_convert()  →  valid Veri DSL or error
```

## Target declaration

Every `.veri.md` must declare its output target in the first Veri DSL block.
All targets produce **pure functions and pure types** — no side effects,
no mutable state, no external effects:

```veri
TARGET fstar-c       # F* → C via Low* / KaRaMeL
TARGET dafny-rust     # Dafny → Rust
TARGET python-assert  # Python runtime @contract enforcement
```

The pipeline reads this. No verification happens without it.

## Pure discipline (all backends)

All Veri DSL specs must be pure — this constraint applies regardless of target:

- Functions are **pure** (`Pure`/`Tot`/`Lemma` in F*, `function`/`predicate`
  in Dafny, no side effects in Python). No `ST`, `Dv`, `ML`, `Exn` effects.
- Types are **pure** — no `HyperStack`, `Heap`, `ST` modules. No mutable
  references, no heap objects, no ST regions.
- In **Python target**: the contract conditions (`REQUIRES`/`ENSURES` bodies)
  must be pure expressions — they are evaluated as guards around the real
  function. The implementation function itself can have side effects.

### F* / Low* specifics

When target is `fstar-c`, the pipeline additionally enforces the Low* subset:
- Low* subset only (required for KaRaMeL C compilation)
- No `ST` effect, no `HyperStack`/`Heap`/`ST` modules
- No `All`, `ML`, `Dv`, `Exn` effects

### Dafny specifics

When target is `dafny-rust`, the pipeline additionally enforces:
- Dafny `function` / `predicate` / `lemma` (no `method` with side effects)
- No `:=` mutations, no `array` mutation, no `new`
- All types must be Dafny-compilable to Rust (no `seq`, no `set` in function signatures)

### Python specifics

When target is `python-assert`, the pipeline generates:
- `_conditions.py` with checked REQUIRES/ENSURES predicates
- `@contract` decorators injected into real Python implementation code
- Runtime assertions enforce the contracts at execution time
- **The contract conditions themselves must be pure expressions** (no I/O,
  no side effects in REQUIRES/ENSURES predicates) — conditions are evaluated
  before/after the real function and must be side-effect-free
- The implementation function does NOT need to be pure — it can have real
  side effects, but the conditions act as guards around it

## Primary API — verify_and_convert

```python
from veri_build.pipeline import verify_and_convert

# For F*-backed specs:
result = verify_and_convert(fstar_code, target='fstar', module_name='MyModule')

# For Dafny-backed specs:
result = verify_and_convert(dafny_code, target='dafny', module_name='MyModule')
```

VerifyConvertResult:
- `result.verified: bool` — did verification pass?
- `result.veri: str | None` — Veri DSL converted from verified code
- `result.error: str | None` — what went wrong

## Secondary API — compile (when user edits Veri DSL)

When the user has finished editing a Veri DSL spec and wants to compile it,
**always use `compile_veri` in a spawned sub-agent** — the process involves
Docker image builds, LLM agent calls, and verifier runs that can take several
minutes.

```python
# In a sub-agent (spawn with sessions_spawn), run:
from veri_build.pipeline import compile_veri, CompilerConfig

result = compile_veri("spec.veri.md", CompilerConfig(
    agent='claude', use_docker=True,  # claude = Anthropic in Docker
))
# Target auto-detected from the Veri DSL spec's target declaration
```

Output per target:
| Target | Output |
|--------|--------|
| `fstar-c` | Verified C via Low* → KaRaMeL |
| `dafny-rust` | Verified Rust |
| `python-assert` | `_conditions.py` + `@contract`-injected implementation |

**Why sub-agent**: `compile_veri` with `use_docker=True` builds the Docker image
(if missing), copies files into the container, launches an agent inside to fill
`# TODO` blocks, runs the target verifier, then runs KaRaMeL (C) or Dafny
(Rust) or generates Python conditions. This is a long-running isolated task —
don't block the main session.

**Output directory**: Compiled artifacts land in a `build/` directory next to the
spec. The agent prompt tells the sub-agent the exact output paths for the
specific backend.

**Credentials**: ANTHROPIC_* env vars are forwarded to Docker automatically.

## Parent-subagent retry protocol

The `compile_veri` parent and LLM child communicate through a signal loop
with up to 3 rounds:

### Signal: `CODE`
The child provides `let` definitions. The parent:
1. Strips markdown fences and type-fixes the code
2. Injects the code into the generated interface
3. Re-runs fstar.exe / dafny verify
4. If verification passes → accepts the code and proceeds to extraction
5. If verification fails → re-prompts with the exact error message

### Signal: `IMPOSSIBLE`
The child claims the spec cannot be satisfied. The parent:
1. **Judges the reasoning**: checks if the impossibility claim is mathematically sound
2. If the parent agrees (the spec truly is contradictory) → stops, reports IMPOSSIBLE to the user
3. If the parent disagrees (the reasoning has a flaw) → re-prompts the child explaining *why* the claim is wrong:
   - "Your proof assumes X, but the spec allows Y"
   - "The constraint you cite is precluded by REQUIRES line N"
   - "You've misread the type of parameter Z — it's a list, not an integer"
4. The parent NEVER silently accepts IMPOSSIBLE — it always validates the reasoning

### Signal: `RETRY`
The child needs something changed (more context, different framing). The parent:
1. Re-prompts with additional context
2. On the 3rd round, RETRY is treated as failure

### Round 2+ feedback
The parent counts implemented functions and tells the child what's still missing:
```
Previous round: 3 of 5 functions implemented. 2 still missing.
  is_sorted — not yet implemented
  insert — not yet implemented
```

If the sub-agent reports a blocker (e.g., missing tool, unsatisfiable constraint),
the main session must either fix the issue and retry, or accept the impossibility
finding after the parent has validated the reasoning. Never stop at "the agent
step didn't produce output" — debug why and fix it.

## HARD RULE: Lint before delivering

**Never present a `.veri.md` file to the user** — whether written, generated, or
converted — unless it passes `lint`. The lint check must be the last step before
showing the file:

```bash
PYTHONPATH=src:src/veri_build/dsl/src python3 -m veri_build.pipeline lint path/to/your.veri.md
```

Expected output:
```
✅ path/to/your.veri.md: lint passed (<target>)
```

If lint reports any error, **do not show the file to the user**. Fix every
parse error first, then re-lint, and only deliver when it passes. A `.veri.md`
that doesn't lint is broken — it cannot be compiled, verified, or used in any
pipeline downstream step.

## User-facing Veri DSL format rules

After lint passes, deliver the `.veri.md`. A `.veri.md` file is a **markdown document**,
not a bare DSL file. Write your
specification in natural language prose, and place Veri DSL inside ` ```veri `
fenced code blocks. The first Veri DSL block must declare the target:

````markdown
# Sorted List Specification

Target: F* → C via Low*/KaRaMeL

```veri
TARGET fstar-c
```

## Element type

Each element has a numeric serial and a string data field.

```veri
class Element:
    serial: nat
    data: string
```
````

After the target declaration, add types, predicates, and function specs in any
order — each inside its own ` ```veri ` code block, with natural language
documentation surrounding it.

## File conventions

| File | Writer | Format | Purpose |
|------|--------|--------|---------|
| `spec.veri.md` | Pipeline | Veri DSL | User-facing — starts with `TARGET fstar-c`, `TARGET dafny-rust`, or `TARGET python-assert` |
| `spec.veri.f.md` | **You** (LLM, temp) | F* | Working file for F* target |
| `spec.veri.dfy.md` | **You** (LLM, temp) | Dafny | Working file for Dafny target |

## Example (F* target)

```python
from veri_build.pipeline import verify_and_convert

# You wrote this in temp spec.veri.f.md — must be pure / Low* for C:
fstar = """
module SortedList

type element = {
    serial: Prims.nat;
    data: Prims.string;
}

let rec is_sorted (lst: list element) : Prims.bool =
    match lst with
    | [] -> true
    | _ :: [] -> true
    | hd1 :: hd2 :: tl -> hd1.serial <= hd2.serial && is_sorted (hd2 :: tl)

type valid_sorted_list = lst:list element{is_sorted lst}

val add_element:
  existing: valid_sorted_list ->
  new_elem: element ->
  Pure valid_sorted_list
    (requires True)
    (ensures (fun result ->
      is_sorted result /\\
      List.Tot.length result = List.Tot.length existing + 1))
"""

# Verify + convert to Veri DSL
result = verify_and_convert(fstar, target='fstar', module_name='SortedList')

if result.verified:
    # result.veri starts with the target declaration
    with open("sorted_list.veri.md", "w") as f:
        f.write(result.veri)
else:
    # result.error tells you what broke
    pass
```

## Reference

- **Veri DSL syntax**: `veri-build/src/veri_build/dsl/README.md`
- **Pipeline API**: `veri-build/docs/API.md`
- **Examples**: `veri-build/examples/`
- **Python backend**: `veri-build/src/veri_build/dsl/src/backend/python/README.md`
