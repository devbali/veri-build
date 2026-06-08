# Circular Buffer (N=8)

A verified fixed-size circular buffer with push, pop, and peek operations.
Written in Veri DSL.

## Buffer Size

```veri
buffer_size: nat = 8
```

## Buffer Type and Invariant

```veri
class CircularBuffer:
    data:  list[int]   # fixed-size list, length = buffer_size
    head:  nat         # read position
    tail:  nat         # write position
    count: nat         # number of elements

def is_valid_buffer(buf: CircularBuffer) -> bool:
    return (buf.head < buffer_size
            and buf.tail < buffer_size
            and buf.count <= buffer_size
            and len(buf.data) == buffer_size)

type ValidBuffer = CircularBuffer WHERE is_valid_buffer(buf)
```

## Push Operation

```veri
def push(buf: ValidBuffer, value: int) -> ValidBuffer:
    REQUIRES True
    ENSURES (is_valid_buffer(result)
             and result.count == (buf.count + 1 if buf.count < buffer_size
                                   else buffer_size))
#TODO (implement push)
```

## Pop Operation

```veri
def pop(buf: ValidBuffer) -> option[(int, ValidBuffer)]:
    REQUIRES True
    ENSURES match result:
        case None:
            buf.count == 0
        case Some(v, new_buf):
            buf.count > 0
            and is_valid_buffer(new_buf)
            and new_buf.count == buf.count - 1
#TODO (implement pop)
```

## Peek Operation

```veri
def peek(buf: ValidBuffer) -> option[int]:
    REQUIRES True
    ENSURES match result:
        case None:
            buf.count == 0
        case Some(v):
            buf.count > 0
#TODO (implement peek)
```
