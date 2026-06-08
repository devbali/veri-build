# Sorted List Example — Dafny Intermediate

_Generated from `sorted_list.veri.md`. LLM works in this file._

## Element Type

```veri
datatype Element = Element(serial: nat, data: string)
```

## Sorted List Type

A sorted list is a sequence of elements with an invariant:

```veri
type sorted_list = seq<Element>

function method is_sorted(lst: sorted_list): bool
{
    match lst {
    case [] => true
    case [_] => true
    case [hd1, ..[hd2, ..tl]] => hd1.serial <= hd2.serial && is_sorted([hd2] + tl)
    }
}

type valid_sorted_list = x: sorted_list | is_sorted(x)
```

## Adding an Element

```veri
function method add_element(
    existing: valid_sorted_list,
    new_elem: Element
): valid_sorted_list
    requires true
    ensures is_sorted(result) && |result| == |existing| + 1

// TODO: implement
```

## Future Work

- Implement `add_element` with a verified insertion sort step
- Add removal function
- Add binary search for lookups
- Prove uniqueness of serial numbers if needed
