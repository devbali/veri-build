# Sorted List Example

This example demonstrates a simple verified data structure: a list of elements that must always remain sorted by serial number.

## Element Type

Each element has a unique serial number and some data:

```veri
TARGET f-star-c

class Element:
    serial: nat
    data:   string
```

## Sorted List Type

A sorted list is a list of elements with an invariant that enforces ordering:

```veri
def is_sorted(lst: list[Element]) -> bool:
    return match lst:
        case []: True
        case [_]: True
        case [hd1, hd2, *tl]: hd1.serial <= hd2.serial and is_sorted([hd2] + tl)

type valid_sorted_list = list[Element] WHERE is_sorted(lst)
```

## Adding an Element

Add new elements while preserving the invariant:

```veri
def add_element(existing: valid_sorted_list, new_elem: Element) -> valid_sorted_list:
    REQUIRES True
    ENSURES (is_sorted(result)
             and len(result) == len(existing) + 1)

#TODO
```

This function should insert a new element into the sorted list while preserving the invariant:

```veri
def add_element(existing: valid_sorted_list, new_elem: Element) -> valid_sorted_list:
    REQUIRES True
    ENSURES (is_sorted(result)
             and len(result) == len(existing) + 1)

#TODO
```

## Future Work

- Implement `add_element` with a verified insertion sort step
- Add removal function
- Add binary search for lookups
- Prove uniqueness of serial numbers if needed
