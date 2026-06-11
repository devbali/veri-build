# veri-build — Formal Verification Pipeline

Write formal specs in **Veri DSL** → lint, compile to C/Rust/Python with
automated proof assistance.

```
.veri.md  ──►  lint (verify interface)  ──►  compile (fill + verify + emit)
```

## Tutorial: Sorted List

Let's walk through the full workflow with a sorted list example.

### 1. Write the spec

Create `sorted_list.veri.md`. A `.veri.md` file is a **markdown document** — you write
your specification in natural language, and Veri DSL goes inside ` ```veri ` fenced
code blocks:

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
    data:   string
```

## Sorting predicate

A list is sorted if for every adjacent pair, the left element's serial is ≤ the right's.

```veri
def is_sorted(lst: list[Element]) -> bool:
    return match lst:
        case []: True
        case [_]: True
        case [hd1, hd2, *tl]: hd1.serial <= hd2.serial and is_sorted([hd2] + tl)
```

## Refined type

```veri
type valid_sorted_list = list[Element] WHERE is_sorted(lst)
```

## Functions

### add_element

Insert a new element into the sorted list, returning the updated list.

```veri
def add_element(existing: valid_sorted_list, new_elem: Element) -> valid_sorted_list:
    REQUIRES True
    ENSURES (is_sorted(result)
             and len(result) == len(existing) + 1)
```
````

Things to notice:
- **`class Element`** — a record type with two fields: `serial: nat`, `data: string`
- **`is_sorted`** — a predicate that pattern-matches on lists (F* `Cons`/`Nil` is
  handled with `[hd1, hd2, *tl]` and `[]` syntax)
- **`valid_sorted_list`** — a refined type: `list[Element]` where `is_sorted(lst)`
- **`add_element`** — a function contract with `REQUIRES`/`ENSURES`. The
  `#TODO` marker tells the pipeline this needs implementation

### 2. Lint the spec

```bash
cd veri-build
python3 -m veri_build.pipeline lint sorted_list.veri.md
```

This checks:
1. All ` ```veri ` blocks parse as valid Veri DSL
2. The linter generates the target language interface (F* `.fst` / Dafny `.dfy`)
   and runs the verifier to confirm the interface is consistent
3. Rejects raw F* or Dafny code inside ` ```veri ` blocks — only Veri DSL is allowed

### 3. Compile (fill TODOs + verify + emit)

The compile step runs a child LLM agent inside a Docker sandbox to fill `#TODO`
blocks, then verifies the result and compiles to the target output:

```bash
python3 -m veri_build.pipeline compile sorted_list.veri.md --agent claude
```

The pipeline:
1. Reads `sorted_list.veri.md`, extracts Veri DSL blocks, builds the AST
2. Launches an LLM agent inside the Docker container with **read-only** access
   to your project files
3. The agent fills `#TODO` blocks with implementation
4. Verifies the result with F* / Dafny
5. Compiles to the target (C via KaRaMeL, Rust, or Python `_conditions.py`)

### 4. What you get

| Target | Output | Example |
|--------|--------|---------|
| `fstar-c` | Verified C via Low* → KaRaMeL | `sorted_list.c` + `sorted_list.h` |
| `dafny-rust` | Verified Rust | `sorted_list.rs` |
| `python-assert` | Runtime `@contract` enforcement | `_conditions.py` + injected decorators |

### 5. Verifying the agent's work

You can also run the pipeline step by step from Python:

```python
from veri_build.pipeline import verify_and_convert, compile_veri, CompilerConfig

result = verify_and_convert(fstar_code, target='fstar', module_name='SortedList')
if result.verified:
    # result.veri is the converted Veri DSL spec
    with open("sorted_list.veri.md", "w") as f:
        f.write(result.veri)
else:
    print(f"Verification failed: {result.error}")

# Full compile (long-running — spawn in a sub-agent):
compile_veri("sorted_list.veri.md", CompilerConfig(agent='claude', use_docker=True))
```

## Veri DSL

Veri DSL is a Pythonic language for writing formal specifications in one
syntax that compiles to three backends: F* (→ C via KaRaMeL), Dafny (→ Rust),
and Python (runtime `@contract` enforcement).

**Full syntax reference**: [`src/veri_build/dsl/README.md`](src/veri_build/dsl/README.md)
— the `dsl/` subdirectory is a separate [`Veri-DSL`](https://github.com/devbali/Veri-DSL)
repository with its own detailed docs, grammar reference, and three backend
implementations (fstar, dafny, python).

### Constructs at a glance

| Construct | Syntax | Backend mapping |
|-----------|--------|-----------------|
| Record types | `class Name: field: type` | F* record / Dafny datatype / Python class |
| Abstract types | `type Name: kind` | F* abstract / Dafny type |
| Type aliases | `type Name = expr` | F* / Dafny type alias |
| Refined types | `type T = Base WHERE pred` | F* refinement / Dafny `where` / runtime assertion |
| Predicates | `def f(x: T) -> bool:` | F* `let` / Dafny `predicate` / Python function |
| Contracts | `REQUIRES` / `ENSURES` | F* `requires/ensures` / Dafny `requires/ensures` / Python `@contract` |
| Quantifiers | `FORALL x IN set: body` | F* `forall` / Dafny `forall` / runtime comprehension |
| Pattern match | `match x: case []: ...` | F* `match` / Dafny `match` / Python 3.10 `match` |
| List ops | `[hd, *tl]`, `len(x)` | `Cons`/`Nil`, `List.Tot.length` / Dafny `seq` / Python list |
| Target marker | `TARGET fstar-c` | Pipeline routing |

## Pure contract discipline (all targets)

REQUIRES/ENSURES conditions must be **pure expressions** — no side effects,
no I/O, no mutation. The target code can have real effects (C writes to
buffers, Rust I/O, Python file operations), but the contracts that guard
them must evaluate without side effects.

## Targets

| Target | Toolchain | Use Case |
|--------|-----------|----------|
| `fstar-c` | F* → Low* → KaRaMeL → C | Embedded, WASM, verified C libraries |
| `dafny-rust` | Dafny → Rust | Verified Rust crates |
| `python-assert` | Python `@contract` | Runtime enforcement in Python apps |

## Pipeline APIs

| API | What it does |
|-----|-------------|
| `verify_and_convert(code, target, name)` | Verify F*/Dafny code + convert to Veri DSL |
| `compile_veri(spec, config)` | Full pipeline: extract → agent → verify → compile |
| `lint_interface(spec, target)` | Parse + verify interface (fast, no agent) |
| `read_spec(path)` | Parse `.veri.md` into `ExtractedSpec` |

## Repository layout

```
veri-build/
├── Dockerfile                 ← verification-builder (F* + Dafny + KaRaMeL)
├── src/veri_build/
│   ├── pipeline.py            ← verify_and_convert, compile_veri
│   ├── lint.py                ← Interface verification
│   ├── fill.py                ← LLM subprocess for TODOs
│   ├── spec.py                ← Veri DSL extraction, AST merging
│   ├── cli.py                 ← CLI dispatch
│   └── dsl/                   ← Veri DSL compiler (submodule)
├── examples/
│   └── sorted_list/           ← Full worked example (this tutorial)
├── docs/
│   ├── API.md
│   └── VERIFICATION-SKILL.md
└── scripts/
    └── compile_parent_subagent_runner.py    ← parent agent loop (inside Docker)
```

## Versioning

The Veri DSL language version is tracked in
[`src/veri_build/dsl/src/VERSION`](src/veri_build/dsl/src/VERSION)
(currently **0.0.1**). Specs may declare their version:

```veri
VERI_VERSION 0.0.1
```

The lint step checks that the spec's `VERI_VERSION` matches the DSL
version. Every commit that changes the Veri DSL language should update
`VERSION` and create a corresponding git tag:

```bash
git tag v$(cat src/veri_build/dsl/src/VERSION)
git push --tags
```

## Reference docs

- **Veri DSL syntax**: `src/veri_build/dsl/README.md`
- **Full API reference**: `docs/API.md`
- **Agent skill instructions**: `docs/VERIFICATION-SKILL.md`
- **Backend development**: `docs/BACKENDS.md`
- **Docker setup**: `Dockerfile` (build with: `docker build -t verification-builder:latest .`)
