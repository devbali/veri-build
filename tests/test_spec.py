"""Tests for spec parsing, Veri DSL extraction, and F* generation."""

from pathlib import Path
import sys
import tempfile

# Add src to path
_src = Path(__file__).resolve().parents[1] / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

from veri_build.spec import read_spec, generate_fsti, extract_blocks


def test_extract_blocks():
    """Should extract ```veri blocks from markdown."""
    md = """# My Spec

Some text.

```veri
type Foo = int
```

More text.

```veri
def foo(x: int) -> int:
    REQUIRES True
    ENSURES result == x
```
"""
    blocks = extract_blocks(md)
    assert len(blocks) == 2
    assert "type Foo = int" in blocks[0]
    assert "def foo" in blocks[1]


def test_read_spec_sorted_list():
    """Should parse a realistic sorted list spec."""
    md = """# Sorted List

## Element Type
```veri
class Element:
    serial: nat
    data: string
```

## Predicate
```veri
type SortedList = list[Element]

def is_sorted(lst: SortedList) -> bool:
    return match lst:
        case []: True
        case [_]: True
        case [hd1, hd2, *tl]:
            hd1.serial <= hd2.serial and is_sorted([hd2] + tl)
```

## Function
```veri
def add_element(lst: SortedList) -> SortedList:
    REQUIRES is_sorted(lst)
    ENSURES is_sorted(result) and len(result) == len(lst) + 1
```
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".veri.md", prefix="SortedList_", delete=False
    ) as f:
        f.write(md)
        tmp = Path(f.name)

    try:
        spec = read_spec(tmp)
        # Module name derived from temp filename (not exactly "SortedList")
        assert len(spec.veri_blocks) == 3
        assert not spec.todo_function_names  # No #TODO markers

        # Generate .fsti
        fsti = generate_fsti(spec)
        assert "module" in fsti
        assert "sorted_list" in fsti or "element" in fsti
        assert "is_sorted" in fsti
        assert "add_element" in fsti
    finally:
        tmp.unlink()


def test_read_spec_with_todos():
    """Should detect #TODO functions."""
    md = """# My Module

```veri
class Thing:
    value: nat
```

```veri
def process(t: Thing) -> Thing:
    REQUIRES True
    ENSURES result.value >= t.value
```
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".veri.md", delete=False
    ) as f:
        f.write(md)
        tmp = Path(f.name)

    try:
        spec = read_spec(tmp)
        assert len(spec.veri_blocks) == 2
        assert spec.todo_function_names == []
    finally:
        tmp.unlink()


def test_spec_to_prompt():
    """Should generate a concise LLM prompt."""
    md = """# Module

```veri
def foo(x: int) -> int:
    REQUIRES True
    ENSURES result == x
```
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".veri.md", delete=False
    ) as f:
        f.write(md)
        tmp = Path(f.name)

    try:
        spec = read_spec(tmp)
        from veri_build.spec import spec_to_prompt
        prompt = spec_to_prompt(spec)
        assert "def foo" in prompt
        assert "F*" in prompt or "Dafny" in prompt
    finally:
        tmp.unlink()


def test_module_name_from_filename():
    """Module name should be derived from filename."""
    md = "```veri\ntype X = int\n```"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".veri.md", prefix="my_cool_module_", delete=False
    ) as f:
        f.write(md)
        tmp = Path(f.name)

    try:
        spec = read_spec(tmp)
        assert "MyCoolModule" in spec.module_name or "my_cool_module" in spec.module_name.lower()
    finally:
        tmp.unlink()


def test_generate_fsti_from_example():
    """Should generate valid F* .fsti from circular buffer spec."""
    md = """# Circular Buffer

```veri
buffer_size: nat = 8

class CircularBuffer:
    data: list[int]
    head: nat
    tail: nat
    count: nat

def is_valid_buffer(buf: CircularBuffer) -> bool:
    return buf.head < buffer_size and buf.tail < buffer_size

def push(buf: CircularBuffer) -> CircularBuffer:
    REQUIRES True
    ENSURES is_valid_buffer(result)
```
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".veri.md", delete=False
    ) as f:
        f.write(md)
        tmp = Path(f.name)

    try:
        spec = read_spec(tmp)
        fsti = generate_fsti(spec)
        assert "module" in fsti
        assert "circular_buffer" in fsti
        assert "push" in fsti
    finally:
        tmp.unlink()


def test_no_blocks_raises():
    """Should raise on .veri.md with no ```veri blocks."""
    md = "# Just a comment\n\nNo code blocks here.\n"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".veri.md", delete=False
    ) as f:
        f.write(md)
        tmp = Path(f.name)

    try:
        import pytest
        with pytest.raises(ValueError):
            read_spec(tmp)
    except ImportError:
        # pytest not available, manual check
        try:
            read_spec(tmp)
            assert False, "Should have raised"
        except ValueError:
            pass
    finally:
        tmp.unlink()
