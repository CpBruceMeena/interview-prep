# Linked Lists

> Python implementation — 10 questions covering core concepts and interview patterns.

LINKED LISTS — Core Concepts & Interview Questions

---

```python
"""
LINKED LISTS — Core Concepts & Interview Questions
===================================================

Core Concepts:
──────────────
• Node-based linear data structure with dynamic size
• Singly linked: Node(value, next) — O(n) access, O(1) insert/delete at head
• Doubly linked: Node(value, prev, next) — O(1) insert/delete at both ends
• No O(1) random access — must traverse from head
• Sentinel/dummy nodes simplify edge case handling
• Important: Always check None before accessing node.next or node.val

Common Patterns:
────────────────
• Slow/Fast pointer (Floyd's cycle detection, find middle)
• Reversal (in-place iterative, recursive)
• Dummy head for edge cases (deleting head node)
• Merge two sorted lists
• Find intersection point (two pointers that switch to the other
  list's head at the end: both walk a + b + c steps, so they meet)
• LRU Cache (doubly linked list + hash map) — see Design Problems
"""

from typing import List, Optional


class ListNode:
    """Singly linked list node."""
    def __init__(self, val: int = 0, next_node: Optional['ListNode'] = None):
        self.val = val
        self.next = next_node


# Helper to create linked list from list
def list_to_linked(arr: List[int]) -> Optional[ListNode]:
    dummy = ListNode()
    current = dummy
    for val in arr:
        current.next = ListNode(val)
        current = current.next
    return dummy.next


# Helper to convert linked list to list
def linked_to_list(head: Optional[ListNode]) -> List[int]:
    result = []
    while head:
        result.append(head.val)
        head = head.next
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Reverse a Linked List (Iterative & Recursive)
# ════════════════════════════════════════════════════════════════════════

def reverse_list_iterative(head: Optional[ListNode]) -> Optional[ListNode]:
    """
    QUESTION:
    ─────────
    Reverse a singly linked list.

    Example:
        Input: 1 → 2 → 3 → 4 → 5
        Output: 5 → 4 → 3 → 2 → 1

    THOUGHT PROCESS:
    ────────────────
    1. Iterative: Three pointers (prev, current, next)
       - Save next, redirect current.next to prev, advance prev and current
       - O(n) time, O(1) space
    2. Recursive: Assume rest is reversed, point head.next.next = head
       - Base case: empty or single node
       - O(n) time, O(n) space (call stack)

    COMPLEXITY:
    ──────────
    Time: O(n) — Visit each node once
    Space: O(1) — Only three pointers
    """
    prev = None
    current = head

    while current:
        next_node = current.next  # Save next
        current.next = prev       # Reverse link
        prev = current            # Move prev forward
        current = next_node       # Move current forward

    return prev


def reverse_list_recursive(head: Optional[ListNode]) -> Optional[ListNode]:
    """Recursive reverse — elegant but uses O(n) call stack space."""
    if not head or not head.next:
        return head

    new_head = reverse_list_recursive(head.next)
    head.next.next = head
    head.next = None
    return new_head


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Detect Cycle in Linked List
# ════════════════════════════════════════════════════════════════════════

def has_cycle(head: Optional[ListNode]) -> bool:
    """
    QUESTION:
    ─────────
    Given a linked list, determine if it has a cycle.

    Example:
        Input: 3 → 2 → 0 → -4 → (back to index 1)
        Output: true

    THOUGHT PROCESS:
    ────────────────
    1. Hash set: Store visited nodes — O(n) time, O(n) space
    2. Floyd's Cycle Detection (Tortoise & Hare):
       - Slow pointer moves 1 step, fast moves 2 steps
       - If they meet, there's a cycle
       - If fast reaches end (None), no cycle
    3. Why O(1) space? Only two pointers, no extra storage
    4. Why must they meet? Once both are inside the cycle, the gap
       from fast to slow shrinks by exactly 1 per step, so it hits 0
       before fast can jump over slow (it cannot skip a gap of 1).
    5. Compare nodes by identity (`is`), never by value: two distinct
       nodes can hold equal values.

    COMPLEXITY:
    ──────────
    Time: O(n) — Linear in number of nodes
    Space: O(1) — Only two pointers
    """
    slow = fast = head

    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next
        if slow is fast:
            return True

    return False


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Find Cycle Start
# ════════════════════════════════════════════════════════════════════════

def detect_cycle_start(head: Optional[ListNode]) -> Optional[ListNode]:
    """
    QUESTION:
    ─────────
    Given a linked list with a cycle, return the node where the cycle begins.
    If no cycle, return None.

    THOUGHT PROCESS:
    ────────────────
    1. First, detect cycle using Floyd's algorithm
    2. When slow == fast, reset one pointer to head
    3. Move both pointers at same speed (1 step each)
    4. The point where they meet again is the cycle start
    5. Why this works:
       - Let distance from head to cycle start = a
       - Let distance from cycle start to meeting point = b
       - Slow traveled: a + b
       - Fast traveled: a + b + k*L  (L = cycle length, k ≥ 1 laps)
       - Since fast = 2 * slow: 2(a+b) = a+b+k*L → a = k*L - b
       - So walking a steps from the meeting point lands exactly on the
         cycle start (k*L - b = finish this lap, plus whole laps), and
         walking a steps from head lands there too → they meet there

    COMPLEXITY:
    ──────────
    Time: O(n) — Linear scan
    Space: O(1) — Only pointers
    """
    slow = fast = head

    # Find meeting point
    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next
        if slow is fast:
            # Found cycle, find start
            slow = head
            while slow is not fast:
                slow = slow.next
                fast = fast.next
            return slow

    return None  # No cycle


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Merge Two Sorted Lists
# ════════════════════════════════════════════════════════════════════════

def merge_two_lists(list1: Optional[ListNode], list2: Optional[ListNode]) -> Optional[ListNode]:
    """
    QUESTION:
    ─────────
    Merge two sorted linked lists into one sorted list.

    Example:
        Input: 1 → 2 → 4, 1 → 3 → 4
        Output: 1 → 1 → 2 → 3 → 4 → 4

    THOUGHT PROCESS:
    ────────────────
    1. Dummy head simplifies the initial empty case
    2. Compare heads of both lists, attach smaller one
    3. Advance pointer in the list we took from
    4. When one list is exhausted, attach the remainder of the other
    5. Return dummy.next

    COMPLEXITY:
    ──────────
    Time: O(m + n) — Linear in total nodes
    Space: O(1) — Only pointers (excluding output)
    """
    dummy = ListNode()
    current = dummy

    while list1 and list2:
        if list1.val <= list2.val:
            current.next = list1
            list1 = list1.next
        else:
            current.next = list2
            list2 = list2.next
        current = current.next

    # Attach remaining nodes
    current.next = list1 if list1 else list2

    return dummy.next


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Remove Nth Node From End of List
# ════════════════════════════════════════════════════════════════════════

def remove_nth_from_end(head: Optional[ListNode], n: int) -> Optional[ListNode]:
    """
    QUESTION:
    ─────────
    Given the head of a linked list, remove the nth node from the end
    and return the head. Do this in one pass.

    Example:
        Input: head = 1 → 2 → 3 → 4 → 5, n = 2
        Output: 1 → 2 → 3 → 5

    THOUGHT PROCESS:
    ────────────────
    1. Two-pointer approach with dummy head
    2. Move fast pointer n steps ahead
    3. Move both fast and slow until fast reaches end
    4. Now slow.next is the node to remove
    5. Dummy head handles the case where head node is removed

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass
    Space: O(1) — Only pointers

    EDGE CASES:
    ──────────
    • n == length → removes the head; the dummy node makes this the
      same code path (slow stays on dummy)
    • Single node, n = 1 → returns None
    • Assumes 1 ≤ n ≤ length (LeetCode constraint); otherwise the
      n+1 advance would hit None
    """
    dummy = ListNode(0, head)
    slow = fast = dummy

    # Move fast n+1 steps ahead (to maintain gap)
    for _ in range(n + 1):
        fast = fast.next

    # Move both until fast reaches end
    while fast:
        slow = slow.next
        fast = fast.next

    # Remove nth node from end
    slow.next = slow.next.next

    return dummy.next


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Find Middle of Linked List
# ════════════════════════════════════════════════════════════════════════

def middle_node(head: Optional[ListNode]) -> Optional[ListNode]:
    """
    QUESTION:
    ─────────
    Given a non-empty singly linked list, return the middle node.
    If there are two middle nodes, return the second one.

    Example:
        Input: 1 → 2 → 3 → 4 → 5
        Output: 3
        Input: 1 → 2 → 3 → 4 → 5 → 6
        Output: 4

    THOUGHT PROCESS:
    ────────────────
    1. Two passes: Count nodes, then traverse to middle — O(n)
    2. Single pass with slow/fast pointer:
       - Slow moves 1 step, fast moves 2 steps
       - When fast reaches end, slow is at middle
    3. For even length, slow stops at second middle element

    COMPLEXITY:
    ──────────
    Time: O(n) — Fast covers the list in n/2 iterations
    Space: O(1) — Only pointers

    VARIANT:
    ────────
    For the FIRST middle on even lengths (needed when splitting for merge
    sort), loop on `while fast.next and fast.next.next`.
    """
    slow = fast = head

    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next

    return slow


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Add Two Numbers
# ════════════════════════════════════════════════════════════════════════

def add_two_numbers(l1: Optional[ListNode], l2: Optional[ListNode]) -> Optional[ListNode]:
    """
    QUESTION:
    ─────────
    You are given two non-empty linked lists representing two non-negative
    integers. The digits are stored in reverse order. Add the two numbers
    and return the sum as a linked list.

    Example:
        Input: l1 = 2 → 4 → 3 (342), l2 = 5 → 6 → 4 (465)
        Output: 7 → 0 → 8 (807)

    THOUGHT PROCESS:
    ────────────────
    1. Add digit by digit from the least significant (head of list)
    2. Carry over: (sum) % 10 = digit, (sum) // 10 = carry
    3. Handle different length lists
    4. Handle final carry (e.g., 5+5 = 10 → extra node)
    5. Dummy head pattern for result

    COMPLEXITY:
    ──────────
    Time: O(max(m, n)) — Process each digit of longer number
    Space: O(max(m, n)) — Result list (plus 1 for carry)
    """
    dummy = ListNode()
    current = dummy
    carry = 0

    while l1 or l2 or carry:
        val1 = l1.val if l1 else 0
        val2 = l2.val if l2 else 0

        total = val1 + val2 + carry
        digit = total % 10
        carry = total // 10

        current.next = ListNode(digit)
        current = current.next

        if l1:
            l1 = l1.next
        if l2:
            l2 = l2.next

    return dummy.next


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Palindrome Linked List
# ════════════════════════════════════════════════════════════════════════

def is_palindrome(head: Optional[ListNode]) -> bool:
    """
    QUESTION:
    ─────────
    Given a singly linked list, determine if it's a palindrome.
    Must run in O(n) time and O(1) space.

    Example:
        Input: 1 → 2 → 2 → 1
        Output: true

    THOUGHT PROCESS:
    ────────────────
    1. Three steps:
       a) Find middle of list (slow/fast pointer)
       b) Reverse the second half
       c) Compare first and reversed second half
    2. This avoids O(n) extra space for an array copy
    3. Restore the list by reversing the second half back. Mutating a
       caller's input inside a "read-only" check is a real bug; mention
       it, and that the list is not safe to read concurrently meanwhile.

    COMPLEXITY:
    ──────────
    Time: O(n) — A constant number of linear passes
    Space: O(1) — In-place modifications
    """
    def reverse(head: Optional[ListNode]) -> Optional[ListNode]:
        prev = None
        while head:
            next_node = head.next
            head.next = prev
            prev = head
            head = next_node
        return prev

    # Find middle
    slow = fast = head
    while fast and fast.next:
        slow = slow.next
        fast = fast.next.next

    # Reverse second half
    tail = reverse(slow)
    first_half, second_half = head, tail

    # Compare
    result = True
    while second_half:
        if first_half.val != second_half.val:
            result = False
            break
        first_half = first_half.next
        second_half = second_half.next

    # Restore the original list (slow's predecessor still points at slow)
    reverse(tail)
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: Reverse Nodes in k-Group
# ════════════════════════════════════════════════════════════════════════

def reverse_k_group(head: Optional[ListNode], k: int) -> Optional[ListNode]:
    """
    QUESTION:
    ─────────
    Reverse the nodes of a linked list k at a time. If the number of
    remaining nodes is less than k, leave them as they are. Only change
    links, not values. O(1) extra space.

    Example:
        Input: 1 → 2 → 3 → 4 → 5, k = 2
        Output: 2 → 1 → 4 → 3 → 5

    THOUGHT PROCESS:
    ────────────────
    1. It is Q1 (reverse a list) applied to consecutive segments; the
       hard part is the wiring between segments.
    2. Keep `group_prev` = the node just before the current group
       (a dummy for the first group).
    3. Walk k nodes ahead from group_prev. If we run out, stop: the tail
       stays as it is.
    4. Reverse the k nodes, starting with prev = the node AFTER the group,
       so the reversed group's new tail already points at the rest.
    5. Reconnect: group_prev.next = new group head; the old group head is
       now the group's tail and becomes the next group_prev.

    COMPLEXITY:
    ──────────
    Time: O(n) — Each node is visited twice (count ahead, then reverse)
    Space: O(1) — Pointer juggling only (recursive versions use O(n/k))

    EDGE CASES:
    ──────────
    • k = 1 → unchanged;  k = n → whole list reversed
    • n not a multiple of k → last partial group untouched
    """
    dummy = ListNode(0, head)
    group_prev = dummy

    while True:
        # Find the k-th node of this group
        kth = group_prev
        for _ in range(k):
            kth = kth.next
            if kth is None:
                return dummy.next          # Fewer than k left
        group_next = kth.next

        # Reverse the group; prev starts at group_next to keep it linked
        prev, curr = group_next, group_prev.next
        while curr is not group_next:
            nxt = curr.next
            curr.next = prev
            prev = curr
            curr = nxt

        old_group_head = group_prev.next   # Becomes the group's tail
        group_prev.next = kth              # kth is the new group head
        group_prev = old_group_head


# ════════════════════════════════════════════════════════════════════════
# QUESTION 10: Copy List with Random Pointer
# ════════════════════════════════════════════════════════════════════════

class RandomNode:
    """Node with an extra pointer to any node in the list (or None)."""
    def __init__(self, val: int, next_node: Optional['RandomNode'] = None,
                 random: Optional['RandomNode'] = None):
        self.val = val
        self.next = next_node
        self.random = random


def copy_random_list(head: Optional[RandomNode]) -> Optional[RandomNode]:
    """
    QUESTION:
    ─────────
    Each node has `next` and `random` pointers. Return a deep copy: new
    nodes only, with the same next/random structure.

    THOUGHT PROCESS:
    ────────────────
    1. The problem: when copying node X, X.random's copy may not exist
       yet.
    2. Hash map old → new (two passes: create all copies, then wire next
       and random through the map). O(n) space. This is the answer to
       lead with; it also generalises to Clone Graph (Graphs Q5).
    3. O(1) extra space: interleave copies into the original list
       A → A' → B → B' → ...
       - Pass 1: insert each copy right after its original
       - Pass 2: copy.random = original.random.next (the random's copy
         sits right after it)
       - Pass 3: unweave the two lists, restoring the original
       Implemented below.

    COMPLEXITY:
    ──────────
    Time: O(n) — Three linear passes
    Space: O(1) — Extra beyond the copied nodes themselves

    EDGE CASES:
    ──────────
    • random is None, or points to the node itself
    • Empty list → None
    • The original must be restored exactly (pass 3)
    """
    if not head:
        return None

    # Pass 1: A → A' → B → B' ...
    node = head
    while node:
        node.next = RandomNode(node.val, node.next)
        node = node.next.next

    # Pass 2: set random pointers on the copies
    node = head
    while node:
        if node.random:
            node.next.random = node.random.next
        node = node.next.next

    # Pass 3: separate the lists
    copy_head = head.next
    node = head
    while node:
        copy = node.next
        node.next = copy.next
        copy.next = copy.next.next if copy.next else None
        node = node.next

    return copy_head


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("LINKED LISTS — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Reverse Linked List")
    print("-" * 40)
    head = list_to_linked([1, 2, 3, 4, 5])
    print(f"   Original: {linked_to_list(head)}")
    reversed_head = reverse_list_iterative(head)
    print(f"   Reversed: {linked_to_list(reversed_head)}")

    # Q2 & Q3
    print("\n2️⃣  3️⃣  Cycle Detection")
    print("-" * 40)
    # Create list with cycle: 3 → 2 → 0 → -4 → (back to 2)
    cycle_list = ListNode(3)
    cycle_list.next = ListNode(2)
    cycle_list.next.next = ListNode(0)
    cycle_list.next.next.next = ListNode(-4)
    cycle_list.next.next.next.next = cycle_list.next  # cycle to index 1
    print(f"   has_cycle: {has_cycle(cycle_list)}")
    cycle_start = detect_cycle_start(cycle_list)
    print(f"   cycle_start value: {cycle_start.val}")

    # Q4
    print("\n4️⃣  Merge Two Sorted Lists")
    print("-" * 40)
    l1 = list_to_linked([1, 2, 4])
    l2 = list_to_linked([1, 3, 4])
    merged = merge_two_lists(l1, l2)
    print(f"   List 1: [1, 2, 4]")
    print(f"   List 2: [1, 3, 4]")
    print(f"   Merged: {linked_to_list(merged)}")

    # Q5
    print("\n5️⃣  Remove Nth From End")
    print("-" * 40)
    head = list_to_linked([1, 2, 3, 4, 5])
    print(f"   Original: {linked_to_list(head)}")
    result = remove_nth_from_end(head, 2)
    print(f"   After removing 2nd from end: {linked_to_list(result)}")

    # Q6
    print("\n6️⃣  Middle of Linked List")
    print("-" * 40)
    head = list_to_linked([1, 2, 3, 4, 5])
    mid = middle_node(head)
    print(f"   List: [1, 2, 3, 4, 5]")
    print(f"   Middle: {mid.val}")

    # Q7
    print("\n7️⃣  Add Two Numbers")
    print("-" * 40)
    l1 = list_to_linked([2, 4, 3])  # 342
    l2 = list_to_linked([5, 6, 4])  # 465
    result = add_two_numbers(l1, l2)
    print(f"   l1: [2, 4, 3] (342)")
    print(f"   l2: [5, 6, 4] (465)")
    print(f"   Sum: {linked_to_list(result)} (807)")

    # Q8
    print("\n8️⃣  Palindrome Linked List")
    print("-" * 40)
    head = list_to_linked([1, 2, 2, 1])
    print(f"   List: [1, 2, 2, 1]")
    print(f"   Is palindrome: {is_palindrome(head)}")
    head2 = list_to_linked([1, 2])
    print(f"   List: [1, 2]")
    print(f"   Is palindrome: {is_palindrome(head2)}")

    # Q9
    print("\n9️⃣  Reverse Nodes in k-Group")
    print("-" * 40)
    for k in (2, 3):
        head = list_to_linked([1, 2, 3, 4, 5])
        print(f"   [1, 2, 3, 4, 5], k={k} → {linked_to_list(reverse_k_group(head, k))}")

    # Q10
    print("\n🔟  Copy List with Random Pointer")
    print("-" * 40)
    nodes = [RandomNode(v) for v in (7, 13, 11, 10, 1)]
    for a, b in zip(nodes, nodes[1:]):
        a.next = b
    for i, r in enumerate([None, 0, 4, 2, 0]):
        nodes[i].random = nodes[r] if r is not None else None
    copy = copy_random_list(nodes[0])
    pairs, node = [], copy
    while node:
        pairs.append([node.val, node.random.val if node.random else None])
        node = node.next
    print(f"   Copy as [val, random.val]: {pairs}")
    print(f"   Shares no nodes with original: {copy is not nodes[0]}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()

```

---

[← Back to DSA Overview](../index.md)
