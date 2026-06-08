# Sorted List Example

This example demonstrates a simple verified data structure: a list of elements that must always remain sorted by serial number.

## Element Type

Each element has a unique serial number and some data:

```veri
type element = {
  serial: nat;
  data: string;
}
```

## Sorted List Type

A sorted list is a list of elements with an invariant that enforces ordering:

```veri
type sorted_list = list element

let rec is_sorted (lst: sorted_list) : bool =
  match lst with
  | [] -> true
  | [_] -> true
  | hd1 :: hd2 :: tl -> hd1.serial <= hd2.serial && is_sorted (hd2 :: tl)

type valid_sorted_list = lst:sorted_list{is_sorted lst}
```

## Adding an Element

This function should insert a new element into the sorted list while preserving the invariant:

```veri
val add_element: existing:valid_sorted_list -> new_elem:element
  -> Pure valid_sorted_list
    (requires True)
    (ensures (fun result -> 
      is_sorted result /\ 
      List.Tot.length result = List.Tot.length existing + 1))

#TODO
```

## Future Work

- Implement `add_element` with a verified insertion sort step
- Add removal function
- Add binary search for lookups
- Prove uniqueness of serial numbers if needed
