"""veri-build — formal verification pipeline for Veri DSL specs.

A spec-driven pipeline that takes a .veri.md file (with Veri DSL DSL in ```veri blocks),
verifies the interface with F*, fills #TODO functions via LLM, and compiles to WASM or .so.

Components:
  lint    — Parse Veri DSL → generate .fsti → verify interface with F* (no admits)
  fill    — Fill #TODOs via subprocess LLM (claude, pi, or API)
  verify  — lint + fill + verify + candidate + compile to target
"""

__version__ = "0.0.2"

# ── Make Veri-DSL submodule importable ────────────────────────────────
# The Veri-DSL git submodule lives at src/veri_build/dsl/
# Its Python source is at src/veri_build/dsl/src/
# We add it to sys.path so veri_ast, veri_parser, etc. import directly.
import sys as _sys
from pathlib import Path as _Path

_dsl_src = str(_Path(__file__).resolve().parent / "dsl" / "src")
if _dsl_src not in _sys.path:
    _sys.path.insert(0, _dsl_src)
