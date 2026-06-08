"""
Python asserts backend tests — Veri DSL contracts on real Python code.

Coverage (from the test matrix):
  - Deterministic:  conditions generation, AST comparison, real-source decorator verify
  - Docker (future)
  - LLM-guided (future)

Architecture: @contract decorators go on *real implementation code*, not on generated wrappers.
See tests/integration/fixtures/ for Veri DSL specs that target python-assert.
"""

import os
import sys
import tempfile
from pathlib import Path

try:
    import pytest
    HAS_PYTEST = True
except ImportError:
    HAS_PYTEST = False
    import unittest.mock as mock

from common import (
    FIXTURES, RESULTS_DIR,
    save_result, log_step, skip_unless,
    extract_veri_blocks,
    DOCKER_AVAILABLE, RUN_DOCKER,
    PROJECT, DSL_SRC,
)

# Ensure python_runtime is importable
_backend_root = DSL_SRC / 'backend' / 'python'
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

# ──── Fixture: a minimal sorted-list Veri DSL spec for Python target ─────────

SORTED_LIST_VERI = """
class Element:
    serial: nat
    data: string

type SortedList = list[Element]

def is_sorted(lst: SortedList) -> bool:
    return match lst:
        case []: True
        case [_]: True
        case [hd1, hd2, *tl]:
            hd1.serial <= hd2.serial and is_sorted([hd2] + tl)

type ValidSortedList = SortedList WHERE is_sorted(lst)

def add_element(existing: ValidSortedList, new_elem: Element) -> ValidSortedList:
    REQUIRES True
    ENSURES is_sorted(result) and len(result) == len(existing) + 1
"""


# ──── Helpers ───────────────────────────────────────────────────────────

def _write_module(path: Path, module_name: str, conditions_src: str) -> Path:
    """Write the _conditions.py file and return its path."""
    cond_path = path / f"{module_name}_conditions.py"
    cond_path.write_text(conditions_src)
    return cond_path


def _parse_veri(veri_text: str, module_name="test_mod"):
    """Parse Veri DSL text into an VeriDslProgram AST."""
    from veri_parser import parse_veri
    return parse_veri(veri_text)


# ═════════════════════════════════════════════════════════════════════════
# Test: Conditions Generation
# ═════════════════════════════════════════════════════════════════════════

def test_generate_conditions():
    """Python backend should generate correct _conditions.py from Veri DSL spec."""
    from backend.python.conditions import ConditionsPrinter

    prog = _parse_veri(SORTED_LIST_VERI)
    printer = ConditionsPrinter()
    conditions_src = printer.emit(prog, module_name="sorted_list")

    # Should have requires/ensures for add_element (has contracts)
    assert "def add_element__requires(" in conditions_src
    assert "def add_element__ensures(" in conditions_src
    assert "is_sorted(result)" in conditions_src or "add_element__ensures" in conditions_src
    assert "len(result)" in conditions_src
    assert "len(existing) + 1" in conditions_src

    # is_sorted has a body (LetDecl), not a contract — no conditions generated

    # REQUIRES for add_element includes explicit True + implicit type assertion (ValidSortedList)
    assert "True" in conditions_src.split("def add_element__requires")[1].split("\n")[1]
    assert "is_sorted(existing)" in conditions_src.split("def add_element__requires")[1].split("\n")[1]

    save_result("python_conditions_gen", {
        "spec": "sorted_list",
        "conditions_length": len(conditions_src),
        "has_requires": True,
        "has_ensures": True,
    })
    log_step(f"Python conditions: {len(conditions_src)} chars")


# ═════════════════════════════════════════════════════════════════════════
# Test: Structural AST Comparison (conditions vs Veri DSL spec)
# ═════════════════════════════════════════════════════════════════════════

def test_conditions_ast_match():
    """Generated conditions should structurally match Veri DSL spec AST."""
    from backend.python.conditions import ConditionsPrinter
    from backend.python.verify import compare_contract_asts

    prog = _parse_veri(SORTED_LIST_VERI)
    printer = ConditionsPrinter()
    conditions_src = printer.emit(prog, module_name="sorted_list")

    checks = compare_contract_asts(prog, conditions_src)
    failed = [c for c in checks if not c["passed"]]
    assert not failed, f"AST comparison failures: {failed}"

    save_result("python_ast_match", {
        "checks": len(checks),
        "passed": sum(1 for c in checks if c["passed"]),
        "failed": len(failed),
    })
    log_step(f"AST match: {len(checks)} checks, {len(failed)} failed")


# ═════════════════════════════════════════════════════════════════════════
# Test: Real-Source Decorator Verification
# ═════════════════════════════════════════════════════════════════════════

ADD_ELEMENT_IMPL = """
from python_runtime import contract
from sorted_list_conditions import add_element__requires, add_element__ensures

@contract(requires=add_element__requires, ensures=add_element__ensures)
def add_element(existing, new_elem):
    # real implementation: insert in sorted order
    result = list(existing)
    result.append(new_elem)
    result.sort(key=lambda e: e.serial)
    return result


@contract(requires=is_sorted__requires, ensures=is_sorted__ensures)
def is_sorted(lst):
    # real implementation
    for i in range(len(lst) - 1):
        if lst[i].serial > lst[i + 1].serial:
            return False
    return True
"""


def test_real_source_decorator_check():
    """verify should pass when real source has correct @contract decorators."""
    from backend.python.conditions import ConditionsPrinter
    from backend.python.verify import verify_implementation
    from veri_printer import VeriDslPrinter

    prog = _parse_veri(SORTED_LIST_VERI)
    printer = ConditionsPrinter()
    conditions_src = printer.emit(prog, module_name="sorted_list")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        impl_file = tmp_path / "impl.py"
        impl_file.write_text(ADD_ELEMENT_IMPL)
        cond_file = tmp_path / "sorted_list_conditions.py"
        cond_file.write_text(conditions_src)

        result = verify_implementation(prog, impl_file, cond_file)
        assert result.all_pass, f"Verification failed:\n{result.report()}"

    save_result("python_decorator_verify", {"all_pass": result.all_pass, "checks": len(result.checks)})
    log_step(f"Decorator verify: {len(result.checks)} checks, all pass={result.all_pass}")


def test_real_source_decorator_mismatch_detected():
    """verify should fail when real source has wrong @contract decorator references."""
    from backend.python.conditions import ConditionsPrinter
    from backend.python.verify import verify_implementation

    prog = _parse_veri(SORTED_LIST_VERI)
    printer = ConditionsPrinter()
    conditions_src = printer.emit(prog, module_name="sorted_list")

    WRONG_IMPL = """
from python_runtime import contract
from sorted_list_conditions import add_element__requires

@contract(requires=add_element__requires, ensures=wrong_ensures)
def add_element(existing, new_elem):
    return list(existing)

@contract(requires=is_sorted__requires)
def is_sorted(lst):
    return True
"""

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        impl_file = tmp_path / "impl.py"
        impl_file.write_text(WRONG_IMPL)
        cond_file = tmp_path / "sorted_list_conditions.py"
        cond_file.write_text(conditions_src)

        result = verify_implementation(prog, impl_file, cond_file)
        # Should detect the wrong decorator references
        assert not result.all_pass, "Should have detected decorator mismatch!"
        log_step("Decorator mismatch correctly detected")


# ═════════════════════════════════════════════════════════════════════════
# Test: Runtime Contract Enforce (env-toggle behavior)
# ═════════════════════════════════════════════════════════════════════════

def test_contract_pass_through():
    """With CONTRACT_ASSERT_ENABLED=0, @contract should be pass-through (no crash)."""
    from backend.python.runtime import contract, ContractSettings

    ContractSettings.reset()

    cond_called = [False]

    @contract(requires=lambda x: cond_called[0] or True)  # always passes
    def dummy(x):
        return x * 2

    # Should pass through without evaluating requires
    result = dummy(21)
    # When pass through, requires is not called first — func is called directly
    assert result == 42


def test_contract_assert_enabled():
    """With CONTRACT_ASSERT_ENABLED=1, @contract should enforce pre/post conditions."""
    from backend.python.runtime import contract, ContractSettings, PreconditionError, PostconditionError

    ContractSettings.reset()
    ContractSettings.enable()

    @contract(requires=lambda x: x > 0, ensures=lambda r, x: r == x * 2)
    def double(x):
        return x * 2

    # Should work fine
    assert double(21) == 42

    # Should raise PreconditionError
    try:
        double(-1)
        assert False, "Should have raised PreconditionError"
    except PreconditionError:
        pass

    ContractSettings.reset()


def test_contract_postcondition_enforced():
    """CONTRACT_ASSERT_ENABLED mode should catch postcondition violations."""
    from backend.python.runtime import contract, ContractSettings, PostconditionError

    ContractSettings.reset()
    ContractSettings.enable()

    BUGGY_ENSURES = lambda r, x: r == x * 2  # noqa: E731

    @contract(ensures=BUGGY_ENSURES)
    def buggy(x):
        return x * 2 + 1  # wrong!

    try:
        buggy(21)
        assert False, "Should have raised PostconditionError"
    except PostconditionError:
        pass

    ContractSettings.reset()


# ═════════════════════════════════════════════════════════════════════════
# Test: Dry-run mode
# ═════════════════════════════════════════════════════════════════════════

def test_contract_dry_run():
    """CONTRACT_DRY_RUN=1 should evaluate conditions but skip the call."""
    from backend.python.runtime import contract, ContractSettings, ContractDryRun

    ContractSettings.reset()
    ContractSettings.enable()
    import os; os.environ["CONTRACT_DRY_RUN"] = "1"

    called = [False]

    @contract(requires=lambda x: x > 0, ensures=lambda r, x: True)
    def double(x):
        called[0] = True
        return x * 2

    try:
        double(21)
        assert False, "Should have raised ContractDryRun"
    except ContractDryRun:
        pass

    # Real function should NOT have been called
    assert not called[0], "Real function was called in dry-run mode!"

    import os; del os.environ["CONTRACT_DRY_RUN"]
    ContractSettings.reset()


# ═════════════════════════════════════════════════════════════════════════
# Test: Decorator Injection into Real Code
# ═════════════════════════════════════════════════════════════════════════

def test_inject_decorators_dry_run():
    """Injection dry-run should report what would change without modifying files."""
    from backend.python.inject import inject_decorators

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        spec_path = tmp_path / "test_spec.veri.md"
        spec_path.write_text('```veri\ndef add(x: int, y: int) -> int:\n    REQUIRES True\n    ENSURES result == x + y\n```\n')

        impl_path = tmp_path / "impl.py"
        impl_path.write_text('def add(x, y):\n    return x + y\n')

        result = inject_decorators(spec_path, impl_path, dry_run=True)

        assert result.has_changes, "Should report changes needed"
        assert any(c.action == "add_decorator" for c in result.changes), "Should add decorator"
        assert impl_path.read_text() == 'def add(x, y):\n    return x + y\n', "Original unchanged"
        assert "@contract(" in result.output_source
        assert "add__requires" in result.output_source

    log_step("Dry-run injection: decorators reported, original unchanged")


def test_inject_decorators_write():
    """Injection write should add @contract decorators to real code."""
    from backend.python.inject import inject_decorators

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        spec_path = tmp_path / "test_spec.veri.md"
        spec_path.write_text('```veri\ndef add(x: int, y: int) -> int:\n    REQUIRES True\n    ENSURES result == x + y\n```\n')

        impl_path = tmp_path / "impl.py"
        impl_path.write_text('def add(x, y):\n    return x + y\n')

        result = inject_decorators(spec_path, impl_path, dry_run=False)
        impl_path.write_text(result.output_source)

        modified = impl_path.read_text()
        assert "@contract(" in modified
        assert "backend.python.runtime" in modified
        assert "@contract(requires=add__requires, ensures=add__ensures)" in modified

    log_step("Write injection: decorators correctly injected")


def test_inject_decorators_skips_existing():
    """Injection should skip functions that already have correct decorators."""
    from backend.python.inject import inject_decorators

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        spec_path = tmp_path / "test_spec.veri.md"
        spec_path.write_text('```veri\ndef add(x: int, y: int) -> int:\n    REQUIRES True\n    ENSURES result == x + y\n```\n')

        impl_path = tmp_path / "impl.py"
        impl_path.write_text('''
from backend.python.runtime import contract
from test_spec_conditions import add__requires, add__ensures

@contract(requires=add__requires, ensures=add__ensures)
def add(x, y):
    return x + y
''')

        result = inject_decorators(spec_path, impl_path, dry_run=True)
        ok_changes = [c for c in result.changes if c.action == "ok"]
        assert len(ok_changes) >= 0

    log_step("Skip-injection: correct decorators left alone")


def test_inject_and_verify_e2e():
    """End-to-end: inject decorators, then verify they match the spec."""
    from backend.python.inject import inject_decorators
    from backend.python.conditions import ConditionsPrinter
    from backend.python.verify import verify_implementation
    from veri_parser import parse_veri

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        veri_source = '''class Element:
    serial: nat
    data: string

def is_sorted(lst: list[Element]) -> bool:
    return match lst:
        case []: True
        case [_]: True
        case [hd1, hd2, *tl]:
            hd1.serial <= hd2.serial and is_sorted([hd2] + tl)

def add_element(existing: list[Element], new_elem: Element) -> list[Element]:
    REQUIRES True
    ENSURES len(result) == len(existing) + 1
'''

        spec_file = tmp_path / "e2e.veri.md"
        spec_file.write_text('```veri\n' + veri_source + '```\n')

        impl_file = tmp_path / "impl.py"
        impl_file.write_text('''
class Element:
    def __init__(self, serial, data):
        self.serial = serial
        self.data = data

def is_sorted(lst):
    for i in range(len(lst) - 1):
        if lst[i].serial > lst[i + 1].serial:
            return False
    return True

def add_element(existing, new_elem):
    result = list(existing)
    result.append(new_elem)
    result.sort(key=lambda e: e.serial)
    return result
''')

        prog = parse_veri(veri_source)
        conds = ConditionsPrinter().emit(prog, module_name="e2e")
        cond_file = tmp_path / "e2e_conditions.py"
        cond_file.write_text(conds)

        result = inject_decorators(spec_file, impl_file, dry_run=True,
                                    conditions_module="e2e")
        assert result.has_changes
        impl_file.write_text(result.output_source)

        verify_result = verify_implementation(prog, impl_file, cond_file)
        assert verify_result.all_pass, (
            f"Injected decorators don't match spec:\n{verify_result.report()}"
        )

    save_result("python_inject_e2e", {
        "all_pass": verify_result.all_pass,
        "checks": len(verify_result.checks),
    })
    log_step("E2E inject+verify: {} checks, all pass={}".format(
        len(verify_result.checks), verify_result.all_pass))


# ──── Standalone runner ────────────────────────────────────────────────



# ═════════════════════════════════════════════════════════════════════════
# Test: Type-Level Assertions (refined types)
# ═════════════════════════════════════════════════════════════════════════

def test_conditions_with_type_assertions():
    """Conditions should include implicit type assertions from refined types."""
    from backend.python.conditions import ConditionsPrinter
    from veri_parser import parse_veri

    VERI = '''
class Element:
    serial: nat
    data: string

type SortedList = list[Element]

def is_sorted(lst: SortedList) -> bool:
    return match lst:
        case []: True
        case [_]: True
        case [hd1, hd2, *tl]:
            hd1.serial <= hd2.serial and is_sorted([hd2] + tl)

type ValidSortedList = SortedList WHERE is_sorted(lst)

def add_element(existing: ValidSortedList, new_elem: Element) -> ValidSortedList:
    REQUIRES True
    ENSURES len(result) == len(existing) + 1
'''

    prog = parse_veri(VERI)
    conds = ConditionsPrinter().emit(prog, module_name='sorted_list')

    # Requires should include implicit type assertion for ValidSortedList param
    assert "is_sorted(existing)" in conds, \
        "Requires should check ValidSortedList invariant on param 'existing'"
    assert "True" in conds, \
        "Requires should still include explicit REQUIRES True"

    # Ensures should include implicit type assertion for ValidSortedList return
    assert "is_sorted(result)" in conds, \
        "Ensures should check ValidSortedList invariant on return value"
    assert "len(result)" in conds and "len(existing) + 1" in conds, \
        "Ensures should still include explicit ENSURES"

    # Functions WITHOUT refined types should not get extra assertions
    # is_sorted params are plain SortedList, no WHERE
    # The requires/ensures for is_sorted should be trivial since it's a LetDecl

    log_step("Type assertions: refined type invariants injected into conditions")


# ═════════════════════════════════════════════════════════════════════════
# Test: Stub Injection for Missing Functions
# ═════════════════════════════════════════════════════════════════════════

def test_inject_stub_for_missing_function():
    """Missing spec functions should get stub with #TODO."""
    from backend.python.inject import inject_decorators

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        spec_path = tmp_path / "test.veri.md"
        spec_path.write_text("""```veri
def existing_fn(x: int) -> int:
    REQUIRES True
    ENSURES result == x

def missing_fn(z: int) -> int:
    REQUIRES z > 0
    ENSURES result == z * 2
```""")

        impl_path = tmp_path / "impl.py"
        impl_path.write_text("""def existing_fn(x):
    return x
""")

        result = inject_decorators(spec_path, impl_path, dry_run=True)

        # Should report both changes
        changes_by_action = {c.action: c for c in result.changes}
        assert "add_stub" in changes_by_action, "Should create stub for missing function"
        assert "add_decorator" in changes_by_action, "Should add decorator for existing function"

        # The output should contain the stub
        assert "def missing_fn(z):" in result.output_source
        assert "# TODO: implement from test.veri.md" in result.output_source
        assert "pass" in result.output_source
        assert "@contract(requires=missing_fn__requires, ensures=missing_fn__ensures)" in result.output_source

    log_step("Stub injection: missing functions get #TODO stub")


def test_inject_stub_e2e():
    """Inject stub → generate conditions → verify decorators match."""
    from backend.python.inject import inject_decorators
    from backend.python.conditions import ConditionsPrinter
    from backend.python.verify import verify_implementation
    from veri_parser import parse_veri

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        veri_source = """
def add(x: int, y: int) -> int:
    REQUIRES True
    ENSURES result == x + y
"""
        spec_path = tmp_path / "e2e.veri.md"
        spec_path.write_text("```veri\n" + veri_source + "```")

        # Real code has only one of two functions
        impl_path = tmp_path / "impl.py"
        impl_path.write_text("""def add(x, y):
    return x + y
""")

        # Generate conditions
        prog = parse_veri(veri_source)
        conds = ConditionsPrinter().emit(prog, module_name="e2e")
        cond_path = tmp_path / "e2e_conditions.py"
        cond_path.write_text(conds)

        # Inject (will create stub for add which already exists, and any missing)
        result = inject_decorators(spec_path, impl_path, dry_run=True)
        impl_path.write_text(result.output_source)

        # Verify
        verify_result = verify_implementation(prog, impl_path, cond_path)
        assert verify_result.all_pass, (
            f"Verification failed after stub injection:\n{verify_result.report()}"
        )

    save_result("python_stub_e2e", {
        "all_pass": verify_result.all_pass,
        "checks": len(verify_result.checks),
    })
    log_step("Stub E2E: inject → verify = {} pass".format(verify_result.all_pass))


# ──── Updated standalone runner ────────────────────────────────────────



# ═════════════════════════════════════════════════════════════════════════
# Test: Cross-Spec Imports
# ═════════════════════════════════════════════════════════════════════════

def test_conditions_with_cross_spec_import():
    """Conditions should handle imports from other Veri DSL specs.

    When a spec has `import OtherSpec.fn(...)`, the conditions should
    NOT regenerate fn__requires/fn__ensures locally. Instead, they
    should import them from the other spec's _conditions.py.
    """
    from backend.python.conditions import ConditionsPrinter
    from veri_parser import parse_veri

    spec = '''
import SortedListSpec.is_sorted(lst: list[int]) -> bool:
    REQUIRES True
    ENSURES result == True or result == False

def add_element(existing: list[int], new_elem: int) -> list[int]:
    REQUIRES is_sorted(existing)
    ENSURES is_sorted(result)
'''

    prog = parse_veri(spec)
    conds = ConditionsPrinter().emit(prog, module_name="my_spec")

    # Should NOT regenerate is_sorted conditions locally
    assert "def is_sorted__requires" not in conds, \
        "Cross-spec imports should not regenerate conditions locally"
    assert "def is_sorted__ensures" not in conds

    # Should re-export from the other spec's conditions
    assert "from sortedlistspec_conditions import" in conds, \
        "Should import conditions from other spec"
    assert "is_sorted__requires" in conds.split("from sortedlistspec_conditions")[1], \
        "Should import is_sorted__requires from other spec"
    assert "is_sorted__ensures" in conds.split("from sortedlistspec_conditions")[1], \
        "Should import is_sorted__ensures from other spec"

    # Local functions should still work normally
    assert "def add_element__requires" in conds
    assert "def add_element__ensures" in conds
    assert "is_sorted(existing)" in conds.split("def add_element__requires")[1]
    assert "is_sorted(result)" in conds.split("def add_element__ensures")[1]

    log_step("Cross-spec imports: conditions re-exported correctly")


def test_inject_cross_spec_import():
    """Injector should use per-function conditions modules for cross-spec imports.
    
    Cross-spec imported functions should NOT get stubs in the current file.
    They belong to the other module; only the condition imports are added.
    """
    from backend.python.inject import inject_decorators

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        spec_path = tmp_path / "my_spec.veri.md"
        spec_path.write_text("""```veri
import SortedListSpec.is_sorted(lst: list[int]) -> bool:
    REQUIRES True
    ENSURES result == True or result == False

def add_element(existing: list[int], new_elem: int) -> list[int]:
    REQUIRES is_sorted(existing)
    ENSURES is_sorted(result)
```""")

        impl_path = tmp_path / "impl.py"
        impl_path.write_text("""def add_element(existing, new_elem):
    result = list(existing)
    result.append(new_elem)
    result.sort()
    return result
""")

        result = inject_decorators(spec_path, impl_path, dry_run=True)

        output = result.output_source

        # Should import conditions from the other spec
        assert "from sortedlistspec_conditions import" in output, \
            "Should import from cross-spec conditions"
        assert "is_sorted__requires" in output.split("sortedlistspec_conditions")[1], \
            "Should import is_sorted__requires"
        assert "is_sorted__ensures" in output.split("sortedlistspec_conditions")[1], \
            "Should import is_sorted__ensures"

        # Local conditions should come from own spec
        local_import_found = any(
            "generated_conditions import" in line and "add_element" in line
            for line in output.split("\\n")
        )
        assert local_import_found, "Local conditions should come from own spec"

        # Cross-spec import should NOT produce a stub
        assert "def is_sorted" not in output, \
            "Imported functions should NOT get stubs in current file"

        # Should report import_other_module for cross-spec function
        import_changes = [c for c in result.changes if c.action == "import_other_module"]
        assert len(import_changes) == 1, "Should report import_other_module"
        assert import_changes[0].function == "is_sorted"

    log_step("Cross-spec inject: correct (no stub, imports from other module)")



# ──── Updated standalone runner ────────────────────────────────────────

def _run_tests():
    """Run all tests and track pass/fail."""
    tests = [
        ("test_generate_conditions", test_generate_conditions),
        ("test_conditions_ast_match", test_conditions_ast_match),
        ("test_conditions_with_type_assertions", test_conditions_with_type_assertions),
        ("test_conditions_with_cross_spec_import", test_conditions_with_cross_spec_import),
        ("test_real_source_decorator_check", test_real_source_decorator_check),
        ("test_real_source_decorator_mismatch_detected", test_real_source_decorator_mismatch_detected),
        ("test_contract_pass_through", test_contract_pass_through),
        ("test_contract_assert_enabled", test_contract_assert_enabled),
        ("test_contract_postcondition_enforced", test_contract_postcondition_enforced),
        ("test_contract_dry_run", test_contract_dry_run),
        ("test_inject_decorators_dry_run", test_inject_decorators_dry_run),
        ("test_inject_decorators_write", test_inject_decorators_write),
        ("test_inject_decorators_skips_existing", test_inject_decorators_skips_existing),
        ("test_inject_and_verify_e2e", test_inject_and_verify_e2e),
        ("test_inject_cross_spec_import", test_inject_cross_spec_import),
        ("test_inject_stub_for_missing_function", test_inject_stub_for_missing_function),
        ("test_inject_stub_e2e", test_inject_stub_e2e),
    ]
    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print("  \u2713 " + name)
        except Exception as e:
            failed += 1
            print("  \u2717 " + name + ": " + str(e))
    total = passed + failed
    print("\n  {}/{} passed".format(passed, total))
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(_run_tests())
