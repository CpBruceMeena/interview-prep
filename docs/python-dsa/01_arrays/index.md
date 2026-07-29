# Arrays

> Python implementation — 10 questions covering core concepts and interview patterns.

ARRAYS — Core Concepts & Interview Questions

---

```python
"""
ARRAYS — Core Concepts & Interview Questions
=============================================

Core Concepts:
──────────────
• Contiguous memory allocation — O(1) random access by index
• Static vs Dynamic arrays (Python lists are dynamic/resizable)
• Slicing creates shallow copies: arr[start:stop:step]
• Two-pointer technique for sorted/in-place problems
• Sliding window for subarray/substring optimizations
• Prefix sums for range query optimization
• Kadane's Algorithm for maximum subarray sum

Common Patterns:
────────────────
• Two Pointers (converging, parallel, slow-fast)
• Sliding Window (fixed size, variable size)
• Prefix Sum + Hash Map
• In-place modification
• Cyclic sort (1 to n range)

Key Python Methods:
───────────────────
arr.sort(), sorted(arr), arr.append(), arr.pop(), arr[::-1]
bisect_left/right for binary search on sorted arrays
"""

from typing import List, Optional, Tuple
import time


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Two Sum
# ════════════════════════════════════════════════════════════════════════

def two_sum(nums: List[int], target: int) -> List[int]:
    """
    QUESTION:
    ─────────
    Given an array of integers nums and an integer target, return indices
    of the two numbers that add up to target. Assume exactly one solution.
    You may not use the same element twice.

    Example:
        Input: nums = [2, 7, 11, 15], target = 9
        Output: [0, 1]  (2 + 7 = 9)

    THOUGHT PROCESS:
    ────────────────
    1. Brute Force: Check every pair — O(n²), O(1)
    2. Better: Use hash map to store {value: index}
       - For each number, compute complement = target - num
       - If complement exists in map, we found the pair
       - Otherwise, add current number to map
       - One pass: O(n) time, O(n) space
    3. This is optimal since we must examine each element

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass through the array
    Space: O(n) — Hash map stores up to n elements

    EDGE CASES:
    ──────────
    • Duplicate values — handled because we return on complement found
    • Negative numbers — works with the same logic
    • No solution — constraint says exactly one solution exists
    """
    seen = {}  # value -> index

    for i, num in enumerate(nums):
        complement = target - num
        if complement in seen:
            return [seen[complement], i]
        seen[num] = i

    return []  # Should never reach here per problem constraints


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Maximum Subarray (Kadane's Algorithm)
# ════════════════════════════════════════════════════════════════════════

def max_subarray_sum(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Find the contiguous subarray (containing at least one number) which
    has the largest sum and return its sum.

    Example:
        Input: nums = [-2, 1, -3, 4, -1, 2, 1, -5, 4]
        Output: 6  (subarray [4, -1, 2, 1] sums to 6)

    THOUGHT PROCESS:
    ────────────────
    1. Brute Force: Try all O(n²) subarrays, compute sum — O(n²)
    2. Kadane's Insight:
       - At each position, decide: extend current subarray or start fresh?
       - If current_sum + nums[i] < nums[i], it's better to start fresh
       - Track global maximum across all positions
    3. Why it works: Optimal subarray ending at i uses optimal subarray
       ending at i-1 (optimal substructure)

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass with O(1) operations per element
    Space: O(1) — Only two variables needed
    """
    max_ending_here = nums[0]
    max_so_far = nums[0]

    for i in range(1, len(nums)):
        # Start new or extend? — key insight of Kadane's
        max_ending_here = max(nums[i], max_ending_here + nums[i])
        max_so_far = max(max_so_far, max_ending_here)

    return max_so_far


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Product of Array Except Self
# ════════════════════════════════════════════════════════════════════════

def product_except_self(nums: List[int]) -> List[int]:
    """
    QUESTION:
    ─────────
    Given an integer array nums, return an array output such that
    output[i] is the product of all elements of nums except nums[i].
    Must run in O(n) without using division.

    Example:
        Input: nums = [1, 2, 3, 4]
        Output: [24, 12, 8, 6]

    THOUGHT PROCESS:
    ────────────────
    1. With division: total_product / nums[i] — but division not allowed
    2. Key insight: output[i] = product of elements to the left * product to the right
    3. Two-pass approach:
       - Left pass: Calculate running product from left side
       - Right pass: Multiply with running product from right side
    4. Optimization: Use output array itself for left products, then
       multiply with right products using a single variable

    COMPLEXITY:
    ──────────
    Time: O(n) — Two passes over the array
    Space: O(1) — Output array doesn't count as extra space
    """
    n = len(nums)
    output = [1] * n

    # Left pass: output[i] = product of elements to the left of i
    left_product = 1
    for i in range(n):
        output[i] = left_product
        left_product *= nums[i]

    # Right pass: multiply with product of elements to the right
    right_product = 1
    for i in range(n - 1, -1, -1):
        output[i] *= right_product
        right_product *= nums[i]

    return output


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Container With Most Water
# ════════════════════════════════════════════════════════════════════════

def max_area(height: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given an array height where height[i] represents vertical lines,
    find two lines that together with the x-axis form a container that
    holds the most water.

    Example:
        Input: height = [1, 8, 6, 2, 5, 4, 8, 3, 7]
        Output: 49  (between indices 1 and 8, area = 7 * 7 = 49)

    THOUGHT PROCESS:
    ────────────────
    1. Brute Force: Check all O(n²) pairs — too slow
    2. Two-pointer insight:
       - Start with widest container (pointers at ends)
       - Area = min(height[left], height[right]) * (right - left)
       - The limiting factor is the shorter line
       - To find a larger area, we must move the shorter line inward
         (moving the taller line can only decrease or equal the area)
    3. Why moving the shorter line works:
       - If we move the taller line, area can only decrease
         (width decreases, height ≤ min(shorter, taller) = shorter)
       - Moving the shorter line may find a taller line

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass with two pointers
    Space: O(1) — Only variables
    """
    left, right = 0, len(height) - 1
    max_area_val = 0

    while left < right:
        # Calculate current area
        h = min(height[left], height[right])
        w = right - left
        max_area_val = max(max_area_val, h * w)

        # Move the shorter line inward
        if height[left] < height[right]:
            left += 1
        else:
            right -= 1

    return max_area_val


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Find All Duplicates in Array
# ════════════════════════════════════════════════════════════════════════

def find_duplicates(nums: List[int]) -> List[int]:
    """
    QUESTION:
    ─────────
    Given an array of integers, 1 ≤ a[i] ≤ n (n = size of array),
    some elements appear twice and others once. Find all elements that
    appear twice. Must run in O(n) time and use O(1) extra space.

    Example:
        Input: [4, 3, 2, 7, 8, 2, 3, 1]
        Output: [2, 3]

    THOUGHT PROCESS:
    ────────────────
    1. Count frequencies with hash map — O(n) time, O(n) space; violates space
    2. Key insight: Values are in range [1, n], which match array indices
       - Negate the element at index (value - 1) as a marker
       - If already negative, we've seen it before → it's a duplicate
    3. Why negation works:
       - Each value maps to a unique index
       - Negation marks "visited" without losing information
       - Restore by taking abs() for index calculation

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass
    Space: O(1) — Excluding output list
    """
    result = []

    for num in nums:
        idx = abs(num) - 1  # Value maps to index
        if nums[idx] < 0:
            result.append(abs(num))  # Already marked → duplicate
        else:
            nums[idx] = -nums[idx]  # Mark as visited

    # Restore array (optional, good practice)
    for i in range(len(nums)):
        nums[i] = abs(nums[i])

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Three Sum (Triplets that sum to zero)
# ════════════════════════════════════════════════════════════════════════

def three_sum(nums: List[int]) -> List[List[int]]:
    """
    QUESTION:
    ─────────
    Given an integer array, return all unique triplets [nums[i], nums[j],
    nums[k]] such that i != j != k and nums[i] + nums[j] + nums[k] = 0.

    Example:
        Input: nums = [-1, 0, 1, 2, -1, -4]
        Output: [[-1, -1, 2], [-1, 0, 1]]

    THOUGHT PROCESS:
    ────────────────
    1. Brute Force: Check all O(n³) triplets — too slow
    2. Sort + Two Pointers:
       - Sort the array (enables two-pointer + deduplication)
       - Fix one element, then use two pointers for the remaining two
       - For each nums[i], find pairs in the subarray [i+1:] that sum to -nums[i]
    3. Deduplication strategy:
       - Skip duplicate values for i (if nums[i] == nums[i-1])
       - After finding a valid pair, skip duplicates at both ends
    4. Pruning: If nums[i] > 0, break (can't sum to 0 with sorted array)

    COMPLEXITY:
    ──────────
    Time: O(n²) — Sorting O(n log n) + nested loops O(n²)
    Space: O(1) or O(n) depending on sort implementation
    """
    nums.sort()
    result = []
    n = len(nums)

    for i in range(n - 2):
        # Skip duplicates for the fixed element
        if i > 0 and nums[i] == nums[i - 1]:
            continue

        # Pruning: smallest element > 0, no triplets possible
        if nums[i] > 0:
            break

        left, right = i + 1, n - 1
        target = -nums[i]

        while left < right:
            current_sum = nums[left] + nums[right]

            if current_sum == target:
                result.append([nums[i], nums[left], nums[right]])

                # Skip duplicates at both ends
                while left < right and nums[left] == nums[left + 1]:
                    left += 1
                while left < right and nums[right] == nums[right - 1]:
                    right -= 1

                left += 1
                right -= 1
            elif current_sum < target:
                left += 1
            else:
                right -= 1

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Merge Intervals
# ════════════════════════════════════════════════════════════════════════

def merge_intervals(intervals: List[List[int]]) -> List[List[int]]:
    """
    QUESTION:
    ─────────
    Given an array of intervals where intervals[i] = [start, end],
    merge all overlapping intervals and return the result.

    Example:
        Input: [[1,3],[2,6],[8,10],[15,18]]
        Output: [[1,6],[8,10],[15,18]]

    THOUGHT PROCESS:
    ────────────────
    1. Sort by start time to ensure we process in order
    2. Compare current interval's end with next interval's start:
       - If current_end >= next_start → they overlap, merge (extend end)
       - Otherwise → no overlap, add current to result, move to next
    3. Key insight: Only need to check start ≤ current_end for overlap
       Since sorted by start, if next_start > current_end, it's disjoint

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Sorting is the bottleneck
    Space: O(n) — For sorted intervals (or O(1) if in-place sort)
    """
    if not intervals:
        return []

    # Sort by start time
    intervals.sort(key=lambda x: x[0])
    merged = [intervals[0]]

    for start, end in intervals[1:]:
        last_end = merged[-1][1]

        if start <= last_end:
            # Overlap detected — merge by extending the end
            merged[-1][1] = max(last_end, end)
        else:
            # No overlap — add as new interval
            merged.append([start, end])

    return merged


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: First Missing Positive
# ════════════════════════════════════════════════════════════════════════

def first_missing_positive(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given an unsorted integer array, find the smallest positive integer
    that is not present. Must run in O(n) time and O(1) space.

    Example:
        Input: [3, 4, -1, 1]
        Output: 2

    THOUGHT PROCESS:
    ────────────────
    1. The answer is in range [1, n+1] where n = len(nums)
       - If all numbers 1..n are present, answer is n+1
    2. Use array itself as a hash set via cyclic placement:
       - Place each number x at index (x-1) if x is in [1, n]
       - After placement, scan for first index where value != index+1
    3. Cyclic swap technique:
       - While nums[i] is in [1, n] and not in its correct position:
         swap nums[i] with nums[nums[i] - 1]
       - This is O(n) because each swap puts one number in its place

    COMPLEXITY:
    ──────────
    Time: O(n) — Each element is placed correctly in constant time
    Space: O(1) — In-place swapping
    """
    n = len(nums)

    # Place each number in its correct position using cyclic sort
    for i in range(n):
        while 1 <= nums[i] <= n and nums[i] != nums[nums[i] - 1]:
            # Swap to put nums[i] in its correct position
            correct_idx = nums[i] - 1
            nums[i], nums[correct_idx] = nums[correct_idx], nums[i]

    # Find the first index where value != index + 1
    for i in range(n):
        if nums[i] != i + 1:
            return i + 1

    return n + 1  # All numbers 1..n present


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: Rotate Array
# ════════════════════════════════════════════════════════════════════════

def rotate_array(nums: List[int], k: int) -> None:
    """
    QUESTION:
    ─────────
    Given an array, rotate the array to the right by k steps, in-place.

    Example:
        Input: nums = [1,2,3,4,5,6,7], k = 3
        Output: [5,6,7,1,2,3,4]

    THOUGHT PROCESS:
    ────────────────
    1. Naive: Pop and insert at front k times — O(n·k), O(1)
    2. Extra array: Copy to new array at (i+k)%n positions — O(n), O(n)
    3. Optimal: Reverse-based approach (tricky but brilliant):
       - Reverse entire array: [7,6,5,4,3,2,1]
       - Reverse first k elements: [5,6,7,4,3,2,1]
       - Reverse remaining n-k elements: [5,6,7,1,2,3,4]
    4. Why reversal works: Visualize as taking last k elements to front

    COMPLEXITY:
    ──────────
    Time: O(n) — Three reverses, each O(n)
    Space: O(1) — In-place modifications
    """
    n = len(nums)
    k %= n  # Handle k > n

    def reverse(start: int, end: int) -> None:
        while start < end:
            nums[start], nums[end] = nums[end], nums[start]
            start += 1
            end -= 1

    reverse(0, n - 1)      # Reverse entire array
    reverse(0, k - 1)      # Reverse first k elements
    reverse(k, n - 1)      # Reverse remaining n-k elements


# ════════════════════════════════════════════════════════════════════════
# QUESTION 10: Longest Consecutive Sequence
# ════════════════════════════════════════════════════════════════════════

def longest_consecutive(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given an unsorted array of integers, find the length of the longest
    consecutive elements sequence. Must run in O(n) time.

    Example:
        Input: [100, 4, 200, 1, 3, 2]
        Output: 4  (sequence [1, 2, 3, 4])

    THOUGHT PROCESS:
    ────────────────
    1. Sort and scan — O(n log n), too slow
    2. Hash Set approach:
       - Insert all numbers into a set (O(1) membership check)
       - For each number, check if it's the START of a sequence
         (i.e., num-1 is NOT in the set)
       - If it is, count consecutive numbers in the set
    3. Why O(n) overall:
       - Each number is visited at most twice (once in outer loop,
         once as part of a sequence count)
       - Only sequence starters trigger inner while loops

    COMPLEXITY:
    ──────────
    Time: O(n) — Each element processed constant times
    Space: O(n) — Hash set storage
    """
    num_set = set(nums)
    max_length = 0

    for num in num_set:
        # Only process if this is the START of a sequence
        if num - 1 not in num_set:
            current = num
            length = 1

            while current + 1 in num_set:
                current += 1
                length += 1

            max_length = max(max_length, length)

    return max_length


# ════════════════════════════════════════════════════════════════════════
# DEMO: Run all array problems
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("ARRAYS — Interview Questions Demo")
    print("=" * 70)

    # Q1: Two Sum
    print("\n1️⃣  Two Sum")
    print("-" * 40)
    nums, target = [2, 7, 11, 15], 9
    result = two_sum(nums, target)
    print(f"   Input: nums={nums}, target={target}")
    print(f"   Output: {result}  (nums[{result[0]}] + nums[{result[1]}] = {nums[result[0]] + nums[result[1]]})")

    # Q2: Maximum Subarray
    print("\n2️⃣  Maximum Subarray (Kadane's Algorithm)")
    print("-" * 40)
    nums = [-2, 1, -3, 4, -1, 2, 1, -5, 4]
    result = max_subarray_sum(nums)
    print(f"   Input: {nums}")
    print(f"   Maximum Subarray Sum: {result}")

    # Q3: Product Except Self
    print("\n3️⃣  Product of Array Except Self")
    print("-" * 40)
    nums = [1, 2, 3, 4]
    result = product_except_self(nums)
    print(f"   Input: {nums}")
    print(f"   Output: {result}")

    # Q4: Container With Most Water
    print("\n4️⃣  Container With Most Water")
    print("-" * 40)
    height = [1, 8, 6, 2, 5, 4, 8, 3, 7]
    result = max_area(height)
    print(f"   Input: {height}")
    print(f"   Max Area: {result}")

    # Q5: Find Duplicates
    print("\n5️⃣  Find All Duplicates in Array")
    print("-" * 40)
    nums = [4, 3, 2, 7, 8, 2, 3, 1]
    result = find_duplicates(nums[:])  # Pass copy
    print(f"   Input: [4, 3, 2, 7, 8, 2, 3, 1]")
    print(f"   Duplicates: {result}")

    # Q6: Three Sum
    print("\n6️⃣  Three Sum")
    print("-" * 40)
    nums = [-1, 0, 1, 2, -1, -4]
    result = three_sum(nums)
    print(f"   Input: {nums}")
    print(f"   Triplets: {result}")

    # Q7: Merge Intervals
    print("\n7️⃣  Merge Intervals")
    print("-" * 40)
    intervals = [[1, 3], [2, 6], [8, 10], [15, 18]]
    result = merge_intervals(intervals)
    print(f"   Input: {intervals}")
    print(f"   Merged: {result}")

    # Q8: First Missing Positive
    print("\n8️⃣  First Missing Positive")
    print("-" * 40)
    nums = [3, 4, -1, 1]
    result = first_missing_positive(nums[:])  # Pass copy
    print(f"   Input: [3, 4, -1, 1]")
    print(f"   First Missing Positive: {result}")

    # Q9: Rotate Array
    print("\n9️⃣  Rotate Array")
    print("-" * 40)
    nums = [1, 2, 3, 4, 5, 6, 7]
    k = 3
    original = nums[:]
    rotate_array(nums, k)
    print(f"   Input: {original}, k={k}")
    print(f"   Rotated: {nums}")

    # Q10: Longest Consecutive Sequence
    print("\n🔟  Longest Consecutive Sequence")
    print("-" * 40)
    nums = [100, 4, 200, 1, 3, 2]
    result = longest_consecutive(nums)
    print(f"   Input: {nums}")
    print(f"   Longest Consecutive Length: {result}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()

```

---

[← Back to DSA Overview](../index.md)
