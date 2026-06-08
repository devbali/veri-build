"""
DSL completeness (Flow 7) — cross-backend AST parity check.

Verifies that all three backends (F*, Dafny, Python) support the same
Veri DSL AST node types. Gaps are expected for language-specific features.
"""

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
    pytest = types.ModuleType('pytest')
    pytest.mark = _FakeMark()


from common import (
    FIXTURES, RESULTS_DIR,
    save_result, log_step, skip_unless,
    DOCKER_AVAILABLE,
)


# ═════════════════════════════════════════════════════════════════════════
# Flow 7: DSL Completeness
# ═════════════════════════════════════════════════════════════════════════

def test_dsl_completeness():
    """Flow 7: Run the DSL completeness checker across all backends."""
    from backend.completeness import CompletenessChecker, check_all_backends

    report = check_all_backends()

    save_result("flow7_dsl_completeness", {
        "declarations": f"{report.declarations_covered}/{report.declarations_total}",
        "types": f"{report.types_covered}/{report.types_total}",
        "expressions": f"{report.expressions_covered}/{report.expressions_total}",
        "patterns": f"{report.patterns_covered}/{report.patterns_total}",
        "gaps": len(report.gaps),
        "gaps_detail": [str(g) for g in report.gaps],
        "backends": report.backends,
    })

    log_step(f"DSL completeness: {len(report.gaps)} gaps (expected asymmetry)")
    print(report.summary())

    # Known asymmetry gaps that are expected (language-specific features):
    KNOWN_ERROR_GAPS = {
        "FriendDecl",   # F*-specific open module, not in Dafny
        "PragmaDecl",   # Dafny uses 'pragma', F* doesn't need it
        "BufferType",   # Dafny supports native buffer types, F* uses Low*
        "ListType",     # Dafny uses seq<T>, not list[T]
        "OptionType",   # Dafny has Option, F* uses option but differently
    }
    new_gaps = [
        g for g in report.error_gaps
        if g.node_type not in KNOWN_ERROR_GAPS
    ]
    if new_gaps:
        raise AssertionError(f"New unexpected gaps found: {new_gaps}")
    log_step("No new gaps beyond expected asymmetry")

    # Warnings-only count (keyword & single-backend): these are expected
    log_step(f"  {len(report.warning_gaps)} expected asymmetry warnings")


# ──── Run directly (no pytest) ─────────────────────────────────────────

def _main():
    """Fallback runner so this works without pytest."""
    from backend.completeness import CompletenessChecker
    checker = CompletenessChecker()
    report = checker.check_all()
    print(report.summary())
    sys.exit(0)


if __name__ == '__main__':
    _main()
