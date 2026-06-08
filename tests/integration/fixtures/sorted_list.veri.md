# Sorted List — F* Target (Veri DSL → F* → C via Low*/KaRaMeL)

Integration test fixture for the F* → C pipeline.

```veri
TARGET f-star-c

class Element:
    serial: nat
    data: string

type SortedList = list[Element]

def is_sorted(lst: SortedList) -> bool:
    return match lst:
        case []:
            True
        case [_]:
            True
        case [hd1, hd2, *tl]:
            hd1.serial <= hd2.serial and is_sorted([hd2] + tl)

type ValidSortedList = SortedList WHERE is_sorted(lst)

def add_element(existing: ValidSortedList, new_elem: Element) -> ValidSortedList:
    REQUIRES True
    ENSURES is_sorted(result) and len(result) == len(existing) + 1
```
