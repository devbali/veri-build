# Circular Buffer — Dafny Target (Veri DSL → Dafny → Rust)

Integration test fixture for the Dafny → Rust pipeline.

```veri
TARGET dafny-rust

buffer_size: nat = 8

class CircularBuffer:
    data: list[int]
    head: nat
    tail: nat
    count: nat

def is_valid_buffer(buf: CircularBuffer) -> bool:
    return buf.head < buffer_size and buf.tail < buffer_size and buf.count <= buffer_size

type ValidBuffer = CircularBuffer WHERE is_valid_buffer(buf)

def push(buf: ValidBuffer, value: int) -> ValidBuffer:
    REQUIRES True
    ENSURES is_valid_buffer(result) and result.count == buf.count + 1
```
