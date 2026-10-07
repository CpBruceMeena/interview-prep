# Hashing

> Python implementation — 9 questions covering core concepts and interview patterns.

HASHING — Core Concepts & Interview Questions

---

```python
"""
HASHING — Core Concepts & Interview Questions
==============================================

Core Concepts:
──────────────
• Hash function maps keys to array indices — O(1) average lookup
• Collision resolution: Chaining (linked list) vs Open Addressing (probing)
• CPython dict/set use OPEN ADDRESSING (perturbed probing), not chaining;
  dicts keep insertion order (a language guarantee since Python 3.7)
• Load factor (α = n/m) drives resizing: Java's HashMap resizes at 0.75,
  CPython's dict at about 2/3 full. Lower α = fewer collisions, more memory
• Worst case is O(n) per operation when keys collide (adversarial
  inputs); Java 8+ HashMap turns long chains into red-black trees
• Good hash functions: deterministic, uniform distribution, fast to compute
• Hash tables trade space for time — O(1) operations vs O(n) for arrays

Common Patterns:
────────────────
• Frequency counting (Counter pattern)
• Two-sum variants (complement search)
• Set operations (union, intersection, difference)
• Caching / memoization
• Detecting duplicates / cycles
• Counting subarrays with given sum
"""

from typing import List, Optional, Tuple, Dict
from collections import Counter, defaultdict


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Subarray Sum Equals K
# ════════════════════════════════════════════════════════════════════════

def subarray_sum(nums: List[int], k: int) -> int:
    """
    QUESTION:
    ─────────
    Given an array of integers and an integer k, find the total number
    of subarrays whose sum equals k.

    Example:
        Input: nums = [1, 1, 1], k = 2
        Output: 2  ([1,1] at indices 0-1 and 1-2)

    THOUGHT PROCESS:
    ────────────────
    1. Brute Force: Check all O(n²) subarrays — too slow for large n
    2. Prefix Sum + Hash Map:
       - prefix_sum[j] - prefix_sum[i] = sum of subarray [i+1...j]
       - We need: prefix_sum[j] - prefix_sum[i] = k
       - So: prefix_sum[i] = prefix_sum[j] - k
       - As we iterate, maintain prefix sum and count of how many times
         each prefix sum has been seen
    3. For each position, add count of (current_sum - k) to result
       This gives the number of subarrays ending at current position
    4. Seed {0: 1}: the empty prefix, so subarrays starting at index 0
       are counted.
    5. Why not a sliding window? With negative numbers, growing the
       window can decrease the sum, so there is no monotonic rule for
       when to shrink. Prefix sums work for any sign.

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass through the array
    Space: O(n) — Hash map stores up to n prefix sums

    EDGE CASES:
    ──────────
    • k = 0 with zeros [0,0,0] → 6 (every subarray)
    • Java/Go: prefix sums can overflow int; use long / int64
    """
    prefix_counts = {0: 1}  # prefix_sum -> frequency
    current_sum = 0
    count = 0

    for num in nums:
        current_sum += num
        # Number of subarrays ending here that sum to k
        count += prefix_counts.get(current_sum - k, 0)
        prefix_counts[current_sum] = prefix_counts.get(current_sum, 0) + 1

    return count


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Longest Consecutive Sequence (Hash Set approach)
# ════════════════════════════════════════════════════════════════════════

def longest_consecutive(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given an unsorted array of integers, find the length of the longest
    consecutive elements sequence. Must run in O(n).

    Example:
        Input: [100, 4, 200, 1, 3, 2]
        Output: 4  ([1, 2, 3, 4])

    THOUGHT PROCESS:
    ────────────────
    1. Using a hash set for O(1) membership checks
    2. Only start counting from the beginning of a sequence
       (num-1 not in set)
    3. This ensures O(n) overall (each number checked at most twice)
    4. Iterate over the SET, not the list: with many duplicates of a
       sequence start, looping over the list would re-walk the same run
       (Same problem as Arrays Q10; kept here as the hash-set pattern.)

    COMPLEXITY:
    ──────────
    Time: O(n) — Each number processed in constant time
    Space: O(n) — Hash set
    """
    num_set = set(nums)
    max_len = 0

    for num in num_set:
        if num - 1 not in num_set:
            current = num
            length = 1
            while current + 1 in num_set:
                current += 1
                length += 1
            max_len = max(max_len, length)

    return max_len


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Top K Frequent Elements
# ════════════════════════════════════════════════════════════════════════

def top_k_frequent(nums: List[int], k: int) -> List[int]:
    """
    QUESTION:
    ─────────
    Given an integer array and an integer k, return the k most frequent
    elements.

    Example:
        Input: nums = [1,1,1,2,2,3], k = 2
        Output: [1, 2]

    THOUGHT PROCESS:
    ────────────────
    1. Count frequencies with hash map — O(n)
    2. Various ways to get top k:
       a) Sort by frequency — O(n log n)
       b) Min-heap of size k — O(n log k)
       c) Bucket sort (frequency as index) — O(n) optimal
    3. Bucket sort approach:
       - Create array of size n+1 where index = frequency
       - Place each number in its frequency bucket
       - Iterate from highest frequency downwards

    COMPLEXITY:
    ──────────
    Time: O(n) — Counting + bucket distribution + gathering
    Space: O(n) — Hash map + bucket array

    TRADE-OFF:
    ──────────
    Bucket sort is O(n) but allocates n+1 buckets. For a stream or when
    k is much smaller than the number of distinct values, a size-k
    min-heap (O(n log k), O(k) extra) is the usual production answer.
    Ties between equal frequencies come back in arbitrary order.
    """
    # Count frequencies
    freq = Counter(nums)

    # Bucket sort by frequency: bucket[i] = numbers with frequency i
    bucket = [[] for _ in range(len(nums) + 1)]
    for num, count in freq.items():
        bucket[count].append(num)

    # Gather top k from highest frequency buckets
    result = []
    for i in range(len(bucket) - 1, 0, -1):
        for num in bucket[i]:
            result.append(num)
            if len(result) == k:
                return result

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Contains Duplicate II (Nearby Duplicates)
# ════════════════════════════════════════════════════════════════════════

def contains_nearby_duplicate(nums: List[int], k: int) -> bool:
    """
    QUESTION:
    ─────────
    Given an array and an integer k, return true if there are two distinct
    indices i and j such that nums[i] == nums[j] and |i - j| ≤ k.

    Example:
        Input: nums = [1,2,3,1], k = 3
        Output: true

    THOUGHT PROCESS:
    ────────────────
    1. Sliding window with hash set
    2. Maintain a window of the previous k elements
    3. For each new element, check if it's already in the window
    4. Remove element that falls out of the window
       (len(window) > k only after an add, and the window holds no
       duplicates, so its size equals the number of indices it covers)
    5. Alternative: dict of value → last index, check i - last <= k

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass
    Space: O(min(k, n)) — Window size bounded by k
    """
    window = set()

    for i, num in enumerate(nums):
        if num in window:
            return True
        window.add(num)
        if len(window) > k:
            window.remove(nums[i - k])  # Remove element that fell out

    return False


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Intersection of Two Arrays II
# ════════════════════════════════════════════════════════════════════════

def intersect(nums1: List[int], nums2: List[int]) -> List[int]:
    """
    QUESTION:
    ─────────
    Given two arrays, return their intersection (including duplicates).

    Example:
        Input: nums1 = [1,2,2,1], nums2 = [2,2]
        Output: [2,2]

    THOUGHT PROCESS:
    ────────────────
    1. Count frequencies of one array
    2. Iterate through second array, if element exists in counter
       and count > 0, add to result and decrement count

    COMPLEXITY:
    ──────────
    Time: O(m + n) — Linear in both arrays
    Space: O(min(m, n)) — Hash map of smaller array

    FOLLOW-UPS INTERVIEWERS ASK:
    ────────────────────────────
    • Both arrays sorted → two pointers, O(1) extra space
    • nums2 on disk, too big for memory → count nums1 in memory and
      stream nums2 in chunks (or external-sort both and merge)
    """
    # Optimize: use smaller array for counting
    if len(nums1) > len(nums2):
        nums1, nums2 = nums2, nums1

    counts = Counter(nums1)
    result = []

    for num in nums2:
        if counts.get(num, 0) > 0:
            result.append(num)
            counts[num] -= 1

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Valid Sudoku
# ════════════════════════════════════════════════════════════════════════

def is_valid_sudoku(board: List[List[str]]) -> bool:
    """
    QUESTION:
    ─────────
    Determine if a 9x9 Sudoku board is valid. Each row, column, and 3x3 box
    must contain digits 1-9 without repetition.

    THOUGHT PROCESS:
    ────────────────
    1. Use hash sets for rows, columns, and boxes
    2. One pass: for each filled cell, check row, column, and box
    3. Box indexing: box_id = (row // 3) * 3 + (col // 3)
    4. Early exit on any duplicate
    5. "Valid" means no rule is broken by the filled cells; it does NOT
       mean the puzzle is solvable (that needs backtracking: see
       Backtracking Q10)

    COMPLEXITY:
    ──────────
    Time: O(9²) = O(1) — Board is always 9x9
    Space: O(9²) = O(1) — Hash sets are bounded
    """
    rows = [set() for _ in range(9)]
    cols = [set() for _ in range(9)]
    boxes = [set() for _ in range(9)]

    for r in range(9):
        for c in range(9):
            val = board[r][c]
            if val == '.':
                continue

            box_id = (r // 3) * 3 + (c // 3)

            if val in rows[r] or val in cols[c] or val in boxes[box_id]:
                return False

            rows[r].add(val)
            cols[c].add(val)
            boxes[box_id].add(val)

    return True


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: LRU Cache (built-in OrderedDict)
# ════════════════════════════════════════════════════════════════════════

from collections import OrderedDict

class LRUCache:
    """
    QUESTION:
    ─────────
    Design a data structure that follows LRU (Least Recently Used) cache
    constraints. Support get(key) and put(key, value) in O(1) time.

    THOUGHT PROCESS:
    ────────────────
    1. Need O(1) access → Hash map
    2. Need O(1) removal of least recently used → Doubly linked list
    3. Python's OrderedDict combines both: dict + doubly linked list
    4. On get: move to end (most recently used)
    5. On put: if full, remove from front, add to end
    6. Interviewers usually ask you to build the hash map + doubly linked
       list yourself; see Design Problems for that version (and LFU).
    7. Not thread-safe: even get() mutates the order, so a shared cache
       needs a lock around both operations.

    COMPLEXITY:
    ──────────
    Time: O(1) — Both get and put
    Space: O(capacity) — Stores at most capacity items
    """

    def __init__(self, capacity: int):
        self._cache = OrderedDict()
        self._capacity = capacity

    def get(self, key: int) -> int:
        if key not in self._cache:
            return -1
        # Move to end (most recently used)
        self._cache.move_to_end(key)
        return self._cache[key]

    def put(self, key: int, value: int) -> None:
        if key in self._cache:
            self._cache.move_to_end(key)
        self._cache[key] = value
        if len(self._cache) > self._capacity:
            # Pop least recently used (first item)
            self._cache.popitem(last=False)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Group Shifted Strings
# ════════════════════════════════════════════════════════════════════════

def group_shifted_strings(strings: List[str]) -> List[List[str]]:
    """
    QUESTION:
    ─────────
    Given a list of strings, group strings that are shifts of each other.
    A shift means each character is moved by the same amount.

    Example:
        Input: ["abc", "bcd", "acef", "xyz", "az", "ba"]
        Output: [["abc","bcd","xyz"], ["acef"], ["az","ba"]]
    Explanation (key = gaps between neighbouring letters, mod 26):
        "abc", "bcd", "xyz" → (1, 1)
        "az" → (25,), "ba" → (-1 mod 26) = (25,) — same key via wrap-around

    THOUGHT PROCESS:
    ────────────────
    1. Generate a canonical key for each string based on character differences
    2. For "abc": diffs are (b-a=1, c-b=1) → key = "1,1"
    3. For wrapping ("ba"): a-b = -1, so normalize with % 26 → 25.
       (Python's % is already non-negative; in Java/Go write
       (diff + 26) % 26 because their % keeps the sign.)
    4. Group by this key; all 1-letter strings share the empty key

    COMPLEXITY:
    ──────────
    Time: O(n * k) — n strings of length k
    Space: O(n * k) — Storing all strings in hash map
    """
    groups = defaultdict(list)

    for s in strings:
        # Build key from consecutive character differences
        diffs = []
        for i in range(1, len(s)):
            diff = (ord(s[i]) - ord(s[i - 1])) % 26
            diffs.append(str(diff))

        key = ','.join(diffs)
        groups[key].append(s)

    return list(groups.values())


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: Design HashMap (Separate Chaining + Resizing)
# ════════════════════════════════════════════════════════════════════════

class MyHashMap:
    """
    QUESTION:
    ─────────
    Design a hash map without built-in hash tables, supporting
    put(key, value), get(key) (return -1 if absent) and remove(key).

    THOUGHT PROCESS:
    ────────────────
    1. An array of buckets; bucket index = hash(key) % capacity.
    2. Collisions: separate chaining (each bucket is a list of [key, value]
       pairs) is simplest to get right. Open addressing (probe for the
       next free slot) is more cache-friendly but needs tombstones on
       delete, otherwise lookups stop early at the hole.
    3. Keep the load factor bounded: when size / capacity exceeds 0.75,
       double the capacity and rehash every entry. Doubling makes the
       total rehash cost O(n) over n inserts → amortized O(1) per put.
    4. Use a prime or power-of-two capacity? Power of two lets
       `hash & (cap - 1)` replace `%`, but then the hash must mix its
       high bits (Java's HashMap XORs h ^ (h >>> 16) for this reason).

    COMPLEXITY:
    ──────────
    Time: O(1) average for put/get/remove (amortized for put);
          O(n) worst case if every key lands in one bucket
    Space: O(n + capacity)

    WHAT THEY PROBE NEXT:
    ─────────────────────
    • Hash flooding (attacker picks colliding keys) → randomized hash
      seeds (Python salts str hashes per process) or tree bins (Java 8+)
    • Concurrent access → lock striping per bucket range, or a
      ConcurrentHashMap-style design with CAS on bucket heads
    • Incremental rehashing (Redis): spread the resize over many
      operations to avoid a latency spike
    """

    _MAX_LOAD = 0.75

    def __init__(self, capacity: int = 8):
        self._capacity = capacity
        self._size = 0
        self._buckets: List[List[list]] = [[] for _ in range(capacity)]

    def _bucket(self, key: int) -> List[list]:
        return self._buckets[hash(key) % self._capacity]

    def put(self, key: int, value: int) -> None:
        bucket = self._bucket(key)
        for pair in bucket:
            if pair[0] == key:
                pair[1] = value          # Update in place
                return
        bucket.append([key, value])
        self._size += 1
        if self._size / self._capacity > self._MAX_LOAD:
            self._resize(self._capacity * 2)

    def get(self, key: int) -> int:
        for k, v in self._bucket(key):
            if k == key:
                return v
        return -1

    def remove(self, key: int) -> None:
        bucket = self._bucket(key)
        for i, (k, _) in enumerate(bucket):
            if k == key:
                bucket[i] = bucket[-1]   # Swap-with-last: O(1) delete
                bucket.pop()
                self._size -= 1
                return

    def _resize(self, new_capacity: int) -> None:
        old = self._buckets
        self._capacity = new_capacity
        self._buckets = [[] for _ in range(new_capacity)]
        for bucket in old:
            for k, v in bucket:
                self._buckets[hash(k) % new_capacity].append([k, v])


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("HASHING — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Subarray Sum Equals K")
    print("-" * 40)
    nums, k = [1, 1, 1], 2
    print(f"   Input: nums={nums}, k={k}")
    print(f"   Count: {subarray_sum(nums, k)}")

    # Q2
    print("\n2️⃣  Longest Consecutive Sequence")
    print("-" * 40)
    nums = [100, 4, 200, 1, 3, 2]
    print(f"   Input: {nums}")
    print(f"   Length: {longest_consecutive(nums)}")

    # Q3
    print("\n3️⃣  Top K Frequent Elements")
    print("-" * 40)
    nums, k = [1, 1, 1, 2, 2, 3], 2
    print(f"   Input: nums={nums}, k={k}")
    print(f"   Top {k}: {top_k_frequent(nums, k)}")

    # Q4
    print("\n4️⃣  Contains Duplicate II")
    print("-" * 40)
    nums, k = [1, 2, 3, 1], 3
    print(f"   Input: nums={nums}, k={k}")
    print(f"   Contains: {contains_nearby_duplicate(nums, k)}")

    # Q5
    print("\n5️⃣  Intersection of Two Arrays II")
    print("-" * 40)
    nums1, nums2 = [1, 2, 2, 1], [2, 2]
    print(f"   Input: {nums1}, {nums2}")
    print(f"   Intersection: {intersect(nums1, nums2)}")

    # Q6
    print("\n6️⃣  Valid Sudoku")
    print("-" * 40)
    valid_board = [
        ["5","3",".",".","7",".",".",".","."],
        ["6",".",".","1","9","5",".",".","."],
        [".","9","8",".",".",".",".","6","."],
        ["8",".",".",".","6",".",".",".","3"],
        ["4",".",".","8",".","3",".",".","1"],
        ["7",".",".",".","2",".",".",".","6"],
        [".","6",".",".",".",".","2","8","."],
        [".",".",".","4","1","9",".",".","5"],
        [".",".",".",".","8",".",".","7","9"]
    ]
    print(f"   Valid board: {is_valid_sudoku(valid_board)}")

    # Q7
    print("\n7️⃣  LRU Cache")
    print("-" * 40)
    cache = LRUCache(2)
    cache.put(1, 1)
    cache.put(2, 2)
    print(f"   get(1): {cache.get(1)}")
    cache.put(3, 3)  # Evicts key 2
    print(f"   get(2) (evicted): {cache.get(2)}")
    cache.put(4, 4)  # Evicts key 1
    print(f"   get(1) (evicted): {cache.get(1)}")
    print(f"   get(3): {cache.get(3)}")
    print(f"   get(4): {cache.get(4)}")

    # Q8
    print("\n8️⃣  Group Shifted Strings")
    print("-" * 40)
    strings = ["abc", "bcd", "acef", "xyz", "az", "ba"]
    print(f"   Input: {strings}")
    print(f"   Groups: {group_shifted_strings(strings)}")

    # Q9
    print("\n9️⃣  Design HashMap")
    print("-" * 40)
    hm = MyHashMap(capacity=2)
    for key in range(5):
        hm.put(key, key * 10)
    hm.put(3, 333)
    hm.remove(1)
    print(f"   put 0..4 (x10), put(3, 333), remove(1)")
    print(f"   get(3): {hm.get(3)}, get(1): {hm.get(1)}, capacity grew to {hm._capacity}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()

```

---

[← Back to DSA Overview](../index.md)
