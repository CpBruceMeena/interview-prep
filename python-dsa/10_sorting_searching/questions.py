"""
SORTING & SEARCHING — Core Concepts & Interview Questions
===========================================================

Sorting Core Concepts:
──────────────────────
• Comparison-based sorts can't beat Ω(n log n) comparisons in the worst
  (or average) case: there are n! orderings and each comparison halves
  the possibilities at best, so log₂(n!) ≈ n log n comparisons
  - Quick Sort: O(n log n) avg, O(n²) worst, O(log n) expected stack (in-place)
  - Merge Sort: O(n log n) guaranteed, O(n) space (stable)
  - Heap Sort: O(n log n) guaranteed, O(1) space (unstable)
• Non-comparison sorts: O(n + k) for integer keys
  - Counting Sort: O(n + k) range, O(k) space
  - Radix Sort: O(d × (n + b)) digits d, base b
• Python's sort (Timsort; Powersort merge policy since 3.11): O(n log n),
  stable, adaptive — O(n) on already-sorted runs. Java sorts objects with
  TimSort and primitives with dual-pivot quicksort (not stable)

Searching Core Concepts:
────────────────────────
• Linear Search: O(n), works on unsorted data
• Binary Search: O(log n), requires sorted data
• Binary Search variants:
  - Lower bound: first index with value >= target (bisect_left)
  - Upper bound: first index with value > target (bisect_right);
    last occurrence = upper bound - 1
  - Search in rotated array
  - Search in infinite array
  - Find peak element

Common Patterns:
────────────────
• Binary search on answer (not just on array) — see Koko, Q10
• Midpoint: write mid = lo + (hi - lo) // 2. In Python (lo + hi) // 2 is
  fine, but in Java/C/Go `lo + hi` can overflow int for large arrays
  (the famous JDK binarySearch bug, fixed in 2006)
• Most binary-search bugs are off-by-one: pick an invariant ("answer is
  in [lo, hi]") and make every branch preserve it
• Divide and conquer
• Partitioning (QuickSelect for kth largest)
• Merging sorted arrays
"""
import random
from typing import List, Optional


# ════════════════════════════════════════════════════════════════════════
# SORTING ALGORITHMS
# ════════════════════════════════════════════════════════════════════════

# --- Quick Sort ---

def quick_sort(arr: List[int]) -> List[int]:
    """
    THOUGHT PROCESS:
    ────────────────
    1. Divide: Pick a pivot, partition array around pivot
       (elements < pivot, pivot, elements > pivot)
    2. Conquer: Recursively sort the two partitions
    3. Combine: Naturally combined since in-place
    4. Pivot selection matters: a random pivot makes the O(n²) worst
       case vanishingly unlikely on sorted / adversarial input
    5. Lomuto partition (used here) degrades to O(n²) when MANY KEYS ARE
       EQUAL (every element goes to one side). Fix with 3-way
       (Dutch-flag) partitioning: < pivot | == pivot | > pivot.
    6. Not stable. Production quicksorts (introsort in C++ std::sort)
       switch to heapsort if recursion gets too deep.

    COMPLEXITY:
    ──────────
    Time: O(n log n) average, O(n²) worst
    Space: O(log n) expected recursion depth; O(n) worst case unless you
           recurse into the smaller side and loop on the larger one
    """
    def _partition(low: int, high: int) -> int:
        # Random pivot to avoid worst-case on sorted arrays
        pivot_idx = random.randint(low, high)
        arr[pivot_idx], arr[high] = arr[high], arr[pivot_idx]
        pivot = arr[high]

        i = low - 1  # Index of smaller element
        for j in range(low, high):
            if arr[j] <= pivot:
                i += 1
                arr[i], arr[j] = arr[j], arr[i]

        arr[i + 1], arr[high] = arr[high], arr[i + 1]
        return i + 1

    def _quick_sort(low: int, high: int) -> None:
        if low < high:
            pi = _partition(low, high)
            _quick_sort(low, pi - 1)
            _quick_sort(pi + 1, high)

    _quick_sort(0, len(arr) - 1)
    return arr


# --- Merge Sort ---

def merge_sort(arr: List[int]) -> List[int]:
    """
    THOUGHT PROCESS:
    ────────────────
    1. Divide: Split array into two halves
    2. Conquer: Recursively sort each half
    3. Combine: Merge two sorted halves (two-pointer technique)
    4. Stable sort: Equal elements maintain relative order

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Always, even for sorted input
    Space: O(n) — Temporary array for merging
    """
    if len(arr) <= 1:
        return arr

    mid = len(arr) // 2
    left = merge_sort(arr[:mid])
    right = merge_sort(arr[mid:])

    # Merge
    result = []
    i = j = 0

    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            result.append(left[i])
            i += 1
        else:
            result.append(right[j])
            j += 1

    # Append remaining elements
    result.extend(left[i:])
    result.extend(right[j:])

    return result


# --- Heap Sort ---

def heap_sort(arr: List[int]) -> List[int]:
    """
    THOUGHT PROCESS:
    ────────────────
    1. Build max heap from array (heapify)
    2. Repeatedly extract max: swap root with last, heapify reduced heap
    3. In-place, unstable, O(1) extra space

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Build heap O(n), each extract O(log n)
    Space: O(1) — In-place (excluding Python's overhead)
    """
    n = len(arr)

    def heapify(n: int, i: int) -> None:
        largest = i
        left = 2 * i + 1
        right = 2 * i + 2

        if left < n and arr[left] > arr[largest]:
            largest = left
        if right < n and arr[right] > arr[largest]:
            largest = right

        if largest != i:
            arr[i], arr[largest] = arr[largest], arr[i]
            heapify(n, largest)

    # Build max heap
    for i in range(n // 2 - 1, -1, -1):
        heapify(n, i)

    # Extract elements one by one
    for i in range(n - 1, 0, -1):
        arr[0], arr[i] = arr[i], arr[0]
        heapify(i, 0)

    return arr


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Kth Largest Element in Array (QuickSelect)
# ════════════════════════════════════════════════════════════════════════

def find_kth_largest(nums: List[int], k: int) -> int:
    """
    QUESTION:
    ─────────
    Find the kth largest element in an unsorted array.
    Must beat O(n log n) sorting.

    Example:
        Input: [3,2,1,5,6,4], k = 2
        Output: 5

    THOUGHT PROCESS:
    ────────────────
    1. Sort and index: O(n log n) — trivial but slower
    2. Min-heap of size k: O(n log k) — the right answer for STREAMS
       (one pass, O(k) memory)
    3. QuickSelect: O(n) average, O(n²) worst
       - Partition in DESCENDING order (>= pivot goes left), so the
         answer sits at index k - 1
       - If the pivot lands at k - 1, return it
       - If it lands left of k - 1, search the right part
       - If it lands right of k - 1, search the left part
       - Only ONE side is recursed into: n + n/2 + n/4 ... = O(n)
    4. This is a "selection algorithm" — finds order statistic
    5. Guaranteed O(n): median-of-medians pivot (rarely coded in
       interviews; just name it). Mutates the input — copy if needed.
    6. With many duplicates this 2-way partition degrades (all-equal
       input is O(n²)); 3-way partitioning fixes it.

    COMPLEXITY:
    ──────────
    Time: O(n) average, O(n²) worst (rare with random pivot)
    Space: O(1) — In-place partitioning
    """

    def partition(left: int, right: int) -> int:
        # Random pivot
        pivot_idx = random.randint(left, right)
        nums[pivot_idx], nums[right] = nums[right], nums[pivot_idx]
        pivot = nums[right]

        i = left
        for j in range(left, right):
            if nums[j] >= pivot:  # Note: >= for kth largest
                nums[i], nums[j] = nums[j], nums[i]
                i += 1

        nums[i], nums[right] = nums[right], nums[i]
        return i

    target_idx = k - 1  # 0-indexed
    left, right = 0, len(nums) - 1

    while left <= right:
        pivot_pos = partition(left, right)

        if pivot_pos == target_idx:
            return nums[pivot_pos]
        elif pivot_pos < target_idx:
            left = pivot_pos + 1
        else:
            right = pivot_pos - 1

    return -1


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Search in Rotated Sorted Array
# ════════════════════════════════════════════════════════════════════════

def search_rotated(nums: List[int], target: int) -> int:
    """
    QUESTION:
    ─────────
    There is a sorted array that has been rotated at some pivot unknown
    to you. Search for a target value and return its index, or -1.

    Example:
        Input: nums = [4,5,6,7,0,1,2], target = 0
        Output: 4

    THOUGHT PROCESS:
    ────────────────
    1. Modified binary search — determine which half is sorted
    2. At each step:
       - If nums[mid] == target, return mid
       - If left half is sorted (nums[left] ≤ nums[mid]):
         - If target is in left half, search left
         - Else, search right
       - If right half is sorted:
         - If target is in right half, search right
         - Else, search left
    3. Key insight: One half is always perfectly sorted after rotation
    4. Use <= in nums[left] <= nums[mid]: when left == mid the "left
       half" is the single element at mid, which is sorted.
    5. Assumes distinct values. With duplicates (LeetCode 81),
       nums[left] == nums[mid] == nums[right] hides which side is
       sorted; shrink both ends by one, worst case O(n).

    COMPLEXITY:
    ──────────
    Time: O(log n) — Binary search
    Space: O(1) — Constant space
    """
    left, right = 0, len(nums) - 1

    while left <= right:
        mid = left + (right - left) // 2

        if nums[mid] == target:
            return mid

        # Left half is sorted
        if nums[left] <= nums[mid]:
            if nums[left] <= target < nums[mid]:
                right = mid - 1
            else:
                left = mid + 1
        # Right half is sorted
        else:
            if nums[mid] < target <= nums[right]:
                left = mid + 1
            else:
                right = mid - 1

    return -1


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Find First and Last Position in Sorted Array
# ════════════════════════════════════════════════════════════════════════

def search_range(nums: List[int], target: int) -> List[int]:
    """
    QUESTION:
    ─────────
    Given a sorted array with duplicates, find the first and last position
    of a target value. If not found, return [-1, -1].

    Example:
        Input: nums = [5,7,7,8,8,10], target = 8
        Output: [3, 4]

    THOUGHT PROCESS:
    ────────────────
    1. Two binary searches: one for left boundary, one for right
    2. Left boundary: standard binary search that doesn't stop at first hit
       - When nums[mid] == target, still narrow right bound (to find leftmost)
    3. Right boundary: similar but narrow left bound
    4. Alternative: lo = bisect_left(nums, target),
       hi = bisect_right(nums, target) - 1; found iff lo <= hi

    COMPLEXITY:
    ──────────
    Time: O(log n) — Two binary searches
    Space: O(1) — Constant
    """

    def find_left() -> int:
        left, right = 0, len(nums) - 1
        first = -1
        while left <= right:
            mid = left + (right - left) // 2
            if nums[mid] >= target:
                right = mid - 1
            else:
                left = mid + 1
            if nums[mid] == target:
                first = mid
        return first

    def find_right() -> int:
        left, right = 0, len(nums) - 1
        last = -1
        while left <= right:
            mid = left + (right - left) // 2
            if nums[mid] <= target:
                left = mid + 1
            else:
                right = mid - 1
            if nums[mid] == target:
                last = mid
        return last

    left_idx = find_left()
    if left_idx == -1:
        return [-1, -1]
    return [left_idx, find_right()]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Find Peak Element
# ════════════════════════════════════════════════════════════════════════

def find_peak_element(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    A peak element is strictly greater than its neighbors. Find a peak
    element and return its index. Assume nums[-1] = nums[n] = -∞.

    Example:
        Input: [1, 2, 3, 1]
        Output: 2  (value 3 is a peak)

    THOUGHT PROCESS:
    ────────────────
    1. Linear scan: O(n) — return first element that's > next
    2. Binary search: O(log n)
       - If nums[mid] > nums[mid+1], peak is in left half (including mid)
       - Else, peak is in right half
    3. Why binary search works: if nums[mid] < nums[mid+1], the values
       must eventually come back down (nums[n] = -∞), so some peak
       exists to the right; symmetric on the left. We are guaranteed
       SOME peak, not the global maximum.
    4. Needs adjacent elements to differ (the problem guarantees it);
       with plateaus, binary search can't tell which way to go.

    COMPLEXITY:
    ──────────
    Time: O(log n) — Binary search
    Space: O(1) — Constant
    """
    left, right = 0, len(nums) - 1

    while left < right:
        mid = left + (right - left) // 2
        if nums[mid] > nums[mid + 1]:
            right = mid  # Peak is in left half (mid could be peak)
        else:
            left = mid + 1  # Peak is in right half

    return left


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Find Minimum in Rotated Sorted Array
# ════════════════════════════════════════════════════════════════════════

def find_min_rotated(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Find the minimum element in a rotated sorted array.

    Example:
        Input: [3, 4, 5, 1, 2]
        Output: 1

    THOUGHT PROCESS:
    ────────────────
    1. Compare nums[mid] with nums[right] (not nums[left]):
       - nums[mid] > nums[right] → the drop (and the minimum) is strictly
         right of mid → left = mid + 1
       - otherwise mid..right is sorted, so the minimum is at mid or to
         its left → right = mid (keep mid: it may be the answer)
    2. Loop while left < right; they converge on the minimum.
    3. Why not compare with nums[left]? For an unrotated array,
       nums[left] <= nums[mid] can't tell "rotated, min on the right"
       from "not rotated, min at left" — the classic bug.
    4. Assumes distinct values; with duplicates (LeetCode 154) handle
       nums[mid] == nums[right] with right -= 1 (worst case O(n)).

    COMPLEXITY:
    ──────────
    Time: O(log n) — Binary search
    Space: O(1) — Constant
    """
    left, right = 0, len(nums) - 1

    while left < right:
        mid = left + (right - left) // 2
        if nums[mid] > nums[right]:
            left = mid + 1      # Minimum is right of mid
        else:
            right = mid         # mid could be the minimum

    return nums[left]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Search a 2D Matrix
# ════════════════════════════════════════════════════════════════════════

def search_matrix(matrix: List[List[int]], target: int) -> bool:
    """
    QUESTION:
    ─────────
    Write an efficient algorithm that searches for a value in an m×n matrix.
    Each row is sorted left-to-right, and the first element of each row
    is greater than the last element of the previous row.

    Example:
        Input: matrix = [[1,3,5,7],[10,11,16,20],[23,30,34,60]], target = 3
        Output: true

    THOUGHT PROCESS:
    ────────────────
    1. Treat as a flat sorted array: 2D → 1D index mapping
       row = idx // cols, col = idx % cols
    2. Standard binary search on the flattened array
    3. Time: O(log(m×n)), Space: O(1)
    4. Different problem (LeetCode 240): rows AND columns sorted, but rows
       don't continue each other. Then start at the top-right corner and
       step left (too big) or down (too small): O(m + n).

    COMPLEXITY:
    ──────────
    Time: O(log(m × n)) — Binary search
    Space: O(1)
    """
    if not matrix:
        return False

    rows, cols = len(matrix), len(matrix[0])
    left, right = 0, rows * cols - 1

    while left <= right:
        mid = left + (right - left) // 2
        row = mid // cols
        col = mid % cols
        val = matrix[row][col]

        if val == target:
            return True
        elif val < target:
            left = mid + 1
        else:
            right = mid - 1

    return False


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Time-Based Key-Value Store (Binary Search on Timestamp)
# ════════════════════════════════════════════════════════════════════════

class TimeMap:
    """
    QUESTION:
    ─────────
    Design a time-based key-value store that supports:
    - set(key, value, timestamp): store key with value at given timestamp
    - get(key, timestamp): get the value of key at or before the timestamp
      (previous value if timestamp not exact)

    Example:
        Input:
          set("foo", "bar", 1)
          get("foo", 1) → "bar"
          get("foo", 3) → "bar"  (no value at 3, but value at 1 exists)
          set("foo", "bar2", 4)
          get("foo", 4) → "bar2"
          get("foo", 5) → "bar2"

    THOUGHT PROCESS:
    ────────────────
    1. Store key → list of (timestamp, value) pairs. Appending keeps it
       sorted ONLY because set() timestamps are strictly increasing per
       key (the problem guarantees it); otherwise use insort (O(n)) or a
       balanced tree / sorted container
    2. get: Binary search for largest timestamp ≤ given timestamp
    3. This is bisect_right - 1 on timestamps
    4. This is how MVCC snapshot reads work in databases: find the latest
       version at or before the read timestamp

    COMPLEXITY:
    ──────────
    Set: O(1) amortized
    Get: O(log n) — Binary search on timestamps
    Space: O(n) — Store all values
    """

    def __init__(self):
        self.store = {}  # key → list of [timestamp, value]

    def set(self, key: str, value: str, timestamp: int) -> None:
        if key not in self.store:
            self.store[key] = []
        self.store[key].append([timestamp, value])

    def get(self, key: str, timestamp: int) -> str:
        if key not in self.store:
            return ""
        values = self.store[key]

        # Binary search for largest timestamp ≤ given timestamp
        left, right = 0, len(values) - 1
        result = ""

        while left <= right:
            mid = left + (right - left) // 2
            if values[mid][0] <= timestamp:
                result = values[mid][1]
                left = mid + 1  # Search for potentially larger timestamp
            else:
                right = mid - 1

        return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Find Duplicate Number (Binary Search on Value Range)
# ════════════════════════════════════════════════════════════════════════

def find_duplicate(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given an array of n+1 integers where each integer is in [1, n],
    there is exactly one duplicate number. Find it without modifying
    the array and using O(1) space.

    Example:
        Input: [1, 3, 4, 2, 2]
        Output: 2

    THOUGHT PROCESS:
    ────────────────
    1. Binary search on VALUE range [1, n], not on indices
    2. Count how many numbers are ≤ mid
    3. If count > mid, duplicate is in [1, mid]
       Else, duplicate is in [mid+1, n]
    4. This works due to pigeonhole principle: if count > mid,
       there are more numbers than slots → some number repeated
    5. O(n) alternative: treat i → nums[i] as a linked list. The
       duplicate value is where two indices point to the same node, i.e.
       the start of a cycle → Floyd's algorithm (Linked Lists Q3).

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Log n passes, each counting n elements
    Space: O(1) — Constant
    """
    left, right = 1, len(nums) - 1

    while left < right:
        mid = left + (right - left) // 2
        count = sum(1 for num in nums if num <= mid)

        if count > mid:
            right = mid  # Duplicate in lower half
        else:
            left = mid + 1  # Duplicate in upper half

    return left


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: Counting Inversions (Merge Sort Application)
# ════════════════════════════════════════════════════════════════════════

def count_inversions(arr: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Count the number of inversions in an array. An inversion is a pair
    (i, j) where i < j and arr[i] > arr[j].

    Example:
        Input: [2, 4, 1, 3, 5]
        Output: 3  (2,1), (4,1), (4,3)

    THOUGHT PROCESS:
    ────────────────
    1. Brute force: Check all O(n²) pairs
    2. Modified merge sort: O(n log n)
       - During merge, when we take element from right array,
         the remaining elements in left array are all > this element
         → count += len(left) - i
    3. This is a classic application of divide-and-conquer

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Merge sort
    Space: O(n) — Temporary array for merge
    """

    def merge_sort_count(arr: List[int]) -> int:
        if len(arr) <= 1:
            return 0

        mid = len(arr) // 2
        left_half = arr[:mid]
        right_half = arr[mid:]

        inversions = merge_sort_count(left_half) + merge_sort_count(right_half)

        # Merge and count cross inversions
        i = j = k = 0
        while i < len(left_half) and j < len(right_half):
            if left_half[i] <= right_half[j]:
                arr[k] = left_half[i]
                i += 1
            else:
                arr[k] = right_half[j]
                inversions += len(left_half) - i  # All remaining in left are greater
                j += 1
            k += 1

        # Copy remaining elements
        while i < len(left_half):
            arr[k] = left_half[i]
            i += 1
            k += 1
        while j < len(right_half):
            arr[k] = right_half[j]
            j += 1
            k += 1

        return inversions

    return merge_sort_count(arr[:])  # Don't modify original


# ════════════════════════════════════════════════════════════════════════
# QUESTION 10: Koko Eating Bananas (Binary Search on the Answer)
# ════════════════════════════════════════════════════════════════════════

def min_eating_speed(piles: List[int], h: int) -> int:
    """
    QUESTION:
    ─────────
    piles[i] bananas in each pile. Each hour Koko picks one pile and eats
    up to k bananas from it. Return the minimum integer speed k that lets
    her finish all piles within h hours (h >= len(piles)).

    Example:
        Input: piles = [3, 6, 7, 11], h = 8
        Output: 4

    THOUGHT PROCESS:
    ────────────────
    1. We are not searching an array; we are searching the ANSWER space
       k ∈ [1, max(piles)].
    2. The key property is monotonicity: if speed k works, every speed
       > k also works. So the predicate "can finish at speed k" looks
       like F F F T T T, and we binary search for the first T.
    3. hours(k) = Σ ceil(p / k). Integer ceil: (p + k - 1) // k
       (avoid floats; in Java/Go sum the hours in a long).
    4. Same template: capacity to ship packages in D days, split array
       largest sum, minimum days to make bouquets, smallest divisor.
       Recognise it by "minimise the maximum" / "minimum X such that".

    COMPLEXITY:
    ──────────
    Time: O(n log M) — M = max(piles); log M guesses, O(n) check each
    Space: O(1)
    """
    def hours_needed(k: int) -> int:
        return sum((p + k - 1) // k for p in piles)

    lo, hi = 1, max(piles)          # Invariant: answer is in [lo, hi]
    while lo < hi:
        mid = lo + (hi - lo) // 2
        if hours_needed(mid) <= h:
            hi = mid                # mid works; maybe something smaller does
        else:
            lo = mid + 1            # Too slow
    return lo


# ════════════════════════════════════════════════════════════════════════
# QUESTION 11: Median of Two Sorted Arrays
# ════════════════════════════════════════════════════════════════════════

def find_median_sorted_arrays(nums1: List[int], nums2: List[int]) -> float:
    """
    QUESTION:
    ─────────
    Given two sorted arrays of sizes m and n, return the median of the
    combined data in O(log(min(m, n))) time.

    Example:
        Input: [1, 3], [2]     → 2.0
        Input: [1, 2], [3, 4]  → 2.5

    THOUGHT PROCESS:
    ────────────────
    1. Merge and pick the middle: O(m + n). Fine as a first answer.
    2. Think "partition", not "merge": cut nums1 after i elements and
       nums2 after j elements so that the left side holds exactly half
       of everything: i + j = (m + n + 1) // 2.
    3. The cut is correct when everything on the left is <= everything
       on the right:
         nums1[i-1] <= nums2[j]  and  nums2[j-1] <= nums1[i]
       (missing neighbours count as -inf / +inf).
    4. Binary search i over [0, m] on the SHORTER array:
       - nums1[i-1] > nums2[j] → i is too big, move left
       - nums2[j-1] > nums1[i] → i is too small, move right
    5. Median: odd total → max of the left side;
       even → (max(left) + min(right)) / 2.

    COMPLEXITY:
    ──────────
    Time: O(log(min(m, n))) — Binary search on the shorter array
    Space: O(1)

    EDGE CASES:
    ──────────
    • One array empty → the cut is i = 0, handled by the ±inf sentinels
    • All of nums1 smaller than nums2 (or larger)
    • Searching the longer array instead can give j < 0 or j > n
    """
    if len(nums1) > len(nums2):
        nums1, nums2 = nums2, nums1
    m, n = len(nums1), len(nums2)
    if m + n == 0:
        raise ValueError("median of empty input")
    half = (m + n + 1) // 2
    NEG, POS = float("-inf"), float("inf")

    lo, hi = 0, m
    while lo <= hi:
        i = (lo + hi) // 2            # Elements taken from nums1
        j = half - i                  # Elements taken from nums2
        left1 = nums1[i - 1] if i > 0 else NEG
        right1 = nums1[i] if i < m else POS
        left2 = nums2[j - 1] if j > 0 else NEG
        right2 = nums2[j] if j < n else POS

        if left1 > right2:
            hi = i - 1                # Took too many from nums1
        elif left2 > right1:
            lo = i + 1                # Took too few from nums1
        else:
            if (m + n) % 2:
                return float(max(left1, left2))
            return (max(left1, left2) + min(right1, right2)) / 2

    raise ValueError("inputs must be sorted")


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("SORTING & SEARCHING — Interview Questions Demo")
    print("=" * 70)

    # Sorting Algorithms
    print("\n📊 SORTING ALGORITHMS")
    print("-" * 40)
    test_arr = [64, 34, 25, 12, 22, 11, 90]
    print(f"   Original: {test_arr}")
    print(f"   Quick Sort: {quick_sort(test_arr[:])}")
    print(f"   Merge Sort: {merge_sort(test_arr[:])}")
    print(f"   Heap Sort: {heap_sort(test_arr[:])}")

    # Q1
    print("\n1️⃣  Kth Largest Element (QuickSelect)")
    print("-" * 40)
    nums = [3, 2, 1, 5, 6, 4]
    k = 2
    print(f"   Input: {nums}, k={k}")
    print(f"   {k}th largest: {find_kth_largest(nums[:], k)}")

    # Q2
    print("\n2️⃣  Search in Rotated Sorted Array")
    print("-" * 40)
    nums = [4, 5, 6, 7, 0, 1, 2]
    print(f"   Input: {nums}, target=0")
    print(f"   Index: {search_rotated(nums, 0)}")

    # Q3
    print("\n3️⃣  First and Last Position in Sorted Array")
    print("-" * 40)
    nums = [5, 7, 7, 8, 8, 10]
    print(f"   Input: {nums}, target=8")
    print(f"   Range: {search_range(nums, 8)}")

    # Q4
    print("\n4️⃣  Find Peak Element")
    print("-" * 40)
    nums = [1, 2, 3, 1]
    print(f"   Input: {nums}")
    print(f"   Peak index: {find_peak_element(nums)}")

    # Q5
    print("\n5️⃣  Find Minimum in Rotated Sorted Array")
    print("-" * 40)
    nums = [3, 4, 5, 1, 2]
    print(f"   Input: {nums}")
    print(f"   Minimum: {find_min_rotated(nums)}")

    # Q6
    print("\n6️⃣  Search a 2D Matrix")
    print("-" * 40)
    matrix = [[1, 3, 5, 7], [10, 11, 16, 20], [23, 30, 34, 60]]
    print(f"   Target 3: {search_matrix(matrix, 3)}")
    print(f"   Target 13: {search_matrix(matrix, 13)}")

    # Q7
    print("\n7️⃣  Time-Based Key-Value Store")
    print("-" * 40)
    tm = TimeMap()
    tm.set("foo", "bar", 1)
    print(f"   get(foo, 1): {tm.get('foo', 1)}")
    print(f"   get(foo, 3): {tm.get('foo', 3)}")
    tm.set("foo", "bar2", 4)
    print(f"   get(foo, 4): {tm.get('foo', 4)}")
    print(f"   get(foo, 5): {tm.get('foo', 5)}")

    # Q8
    print("\n8️⃣  Find Duplicate Number")
    print("-" * 40)
    nums = [1, 3, 4, 2, 2]
    print(f"   Input: {nums}")
    print(f"   Duplicate: {find_duplicate(nums)}")

    # Q9
    print("\n9️⃣  Count Inversions")
    print("-" * 40)
    arr = [2, 4, 1, 3, 5]
    print(f"   Input: {arr}")
    print(f"   Inversions: {count_inversions(arr)}")

    # Q10
    print("\n🔟  Koko Eating Bananas (Binary Search on Answer)")
    print("-" * 40)
    piles, h = [3, 6, 7, 11], 8
    print(f"   piles={piles}, h={h}")
    print(f"   Min speed: {min_eating_speed(piles, h)}")

    # Q11
    print("\n1️⃣1️⃣  Median of Two Sorted Arrays")
    print("-" * 40)
    for a, b in (([1, 3], [2]), ([1, 2], [3, 4])):
        print(f"   {a} + {b} → {find_median_sorted_arrays(a, b)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
