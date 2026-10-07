"""
HEAPS (Priority Queue) — Core Concepts & Interview Questions
=============================================================

Core Concepts:
──────────────
• Complete binary tree where parent ≤ children (min-heap) or
  parent ≥ children (max-heap)
• Python's heapq functions operate on a plain list as a MIN-heap
• Max-heap: Python 3.14+ adds heapify_max / heappush_max / heappop_max;
  on older versions (and in most interview environments) store negated
  values (-val) or wrap items in a class with a reversed __lt__. The code
  here negates, so it runs on any Python 3
• No decrease-key and no delete-by-value: push a new entry and skip
  stale ones on pop ("lazy deletion", see Dijkstra and Q8)
• Ties: push (priority, counter, item) so equal priorities never fall
  through to comparing the items themselves
• Heap operations:
  - heappush(heap, val): O(log n)
  - heappop(heap): O(log n) — removes and returns smallest
  - heap[0]: O(1) — peek at smallest element
  - heapify(list): O(n) — converts list to heap in-place (bottom-up
    sift-down; most nodes are near the leaves, so the sum is O(n), not
    O(n log n))
  - nlargest/nsmallest(k, iter): O(n log k)
• Heap property: heap[i] ≤ heap[2*i+1] and heap[i] ≤ heap[2*i+2]

When to Use a Heap:
───────────────────
• Need the smallest/largest element repeatedly
• Need top-k elements from a stream or large collection
• Merging k sorted arrays/lists
• Median from data stream (two heaps: min + max)
• Dijkstra's / Prim's algorithms
• Task scheduling with priorities

Patterns:
────────────────
• Top K elements — min-heap of size k
• Kth Largest — min-heap of size k
• Merge K Sorted — heap of (value, list_index)
• Median — two heaps (max-heap for left half, min-heap for right)
• K Closest Points — max-heap of size k (or sort by distance)
• Sliding Window Median — two heaps with lazy deletion
"""

from typing import List, Optional, Tuple
import heapq


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Kth Largest Element in a Stream
# ════════════════════════════════════════════════════════════════════════

class KthLargest:
    """
    QUESTION:
    ─────────
    Design a class to find the kth largest element in a stream of numbers.
    Kth largest is the kth element in sorted order (1-indexed).

    Example:
        kth = KthLargest(3, [4, 5, 8, 2])
        kth.add(3) → 4
        kth.add(5) → 5
        kth.add(10) → 5
        kth.add(9) → 8
        kth.add(4) → 8

    THOUGHT PROCESS:
    ────────────────
    1. Maintain a min-heap of exactly k elements
    2. The smallest element in this heap is the kth largest
    3. On add:
       - Push the new value
       - If heap size > k, pop the smallest (which is < kth largest)
    4. The top of heap is always the kth largest

    COMPLEXITY:
    ──────────
    Time: O(log k) per add, O(n log k) to initialize
    Space: O(k) — Heap of size k

    EDGE CASE:
    ──────────
    The constructor may get fewer than k numbers (LeetCode guarantees at
    least k after the first add()), so heap[0] is only "kth largest" once
    the heap holds k items.
    """

    def __init__(self, k: int, nums: List[int]):
        self.heap = []
        self.k = k
        for num in nums:
            self.add(num)

    def add(self, val: int) -> int:
        heapq.heappush(self.heap, val)
        if len(self.heap) > self.k:
            heapq.heappop(self.heap)
        return self.heap[0]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Merge k Sorted Lists
# ════════════════════════════════════════════════════════════════════════

class ListNode:
    """Simple singly-linked list node for this problem."""
    def __init__(self, val: int = 0, next_node: Optional['ListNode'] = None):
        self.val = val
        self.next = next_node


def merge_k_lists(lists: List[Optional[ListNode]]) -> Optional[ListNode]:
    """
    QUESTION:
    ─────────
    Merge k sorted linked lists and return one sorted list.

    Example:
        Input: [[1→4→5], [1→3→4], [2→6]]
        Output: [1→1→2→3→4→4→5→6]

    THOUGHT PROCESS:
    ────────────────
    1. Brute Force: Collect all values, sort, rebuild — O(N log N)
    2. Merging lists one by one into the result is O(N·k) — the naive
       trap (early lists get re-scanned k times)
    3. Divide & Conquer: Merge pairs recursively — O(N log k), O(1) extra
    4. Heap-based: Push (value, list_index, node) → O(N log k)
       - Pop smallest, add to result, push next from that list
       - list_index is a tie-breaker: without it, equal values make
         Python compare ListNode objects and raise TypeError
    5. Same pattern as the merge phase of external sorting (k sorted
       runs on disk) and merging sorted SSTables in LSM-tree compaction

    COMPLEXITY:
    ──────────
    Time: O(N log k) — N total nodes, k lists in heap
    Space: O(k) — Heap size + O(1) for pointers
    """
    import heapq

    # Dummy head for result
    dummy = ListNode()
    current = dummy

    # Initial heap: push first node of each list
    heap = []
    for i, node in enumerate(lists):
        if node:
            # Use (value, i, node) — i prevents comparison on node
            heapq.heappush(heap, (node.val, i, node))

    while heap:
        val, i, node = heapq.heappop(heap)
        current.next = node
        current = current.next

        if node.next:
            heapq.heappush(heap, (node.next.val, i, node.next))

    return dummy.next


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Find Median from Data Stream
# ════════════════════════════════════════════════════════════════════════

class MedianFinder:
    """
    QUESTION:
    ─────────
    Design a data structure that supports adding numbers from a data stream
    and finding the median of all numbers added so far.

    Example:
        mf = MedianFinder()
        mf.addNum(1)
        mf.addNum(2)
        mf.findMedian() → 1.5
        mf.addNum(3)
        mf.findMedian() → 2.0

    THOUGHT PROCESS:
    ────────────────
    1. Two heaps approach:
       - Max-heap (stored as negatives): left half of numbers
       - Min-heap: right half of numbers
       - Invariant: left heap size >= right heap size (by at most 1)
       - All elements in left ≤ all elements in right
    FOLLOW-UPS:
       - All numbers in [0, 100]? Keep 101 counters: O(1) add, O(100)
         median.
       - Deletions / sliding window? See Q8 (lazy deletion).
       - Approximate median over huge streams: t-digest or similar
         quantile sketches.
    2. On add:
       - Push to left (max-heap) first
       - Then balance: move largest from left to right
       - Then ensure size invariant
    3. On findMedian:
       - If odd total: top of left heap
       - If even: average of tops of both heaps

    COMPLEXITY:
    ──────────
    addNum: O(log n) — Heap operations
    findMedian: O(1) — Peek at heap tops
    Space: O(n) — Store all numbers
    """

    def __init__(self):
        # Max-heap for left half (store negatives)
        self.left = []   # max-heap
        self.right = []  # min-heap

    def add_num(self, num: int) -> None:
        # Step 1: Add to left heap (as negative for max-heap)
        heapq.heappush(self.left, -num)

        # Step 2: Ensure all elements in left ≤ all in right
        if (self.left and self.right and
                -self.left[0] > self.right[0]):
            val = -heapq.heappop(self.left)
            heapq.heappush(self.right, val)

        # Step 3: Balance sizes — left can have at most 1 more than right
        if len(self.left) > len(self.right) + 1:
            val = -heapq.heappop(self.left)
            heapq.heappush(self.right, val)
        elif len(self.right) > len(self.left):
            val = heapq.heappop(self.right)
            heapq.heappush(self.left, -val)

    def find_median(self) -> float:
        if len(self.left) > len(self.right):
            return -self.left[0]
        return (-self.left[0] + self.right[0]) / 2.0


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: K Closest Points to Origin
# ════════════════════════════════════════════════════════════════════════

def k_closest(points: List[List[int]], k: int) -> List[List[int]]:
    """
    QUESTION:
    ─────────
    Given an array of points where points[i] = [x, y], return the k
    closest points to the origin (0, 0).

    Example:
        Input: points = [[1,3],[-2,2]], k = 1
        Output: [[-2,2]]

    THOUGHT PROCESS:
    ────────────────
    1. Compute squared distance (avoid sqrt for performance)
    2. Three approaches:
       a) Sort by distance — O(n log n)
       b) Max-heap of size k — O(n log k)
       c) QuickSelect — O(n) average
    3. Heap approach: push (-dist, point), keep size k
       - Negative distance gives us max-heap behavior
       - When we find a point closer than the farthest in our heap,
         pop the farthest and add the new one
    4. Squared distances stay exact integers (no float error). In Java,
       x*x + y*y can overflow int for coordinates near 46341; use long.
    5. Result order is arbitrary (heap order), which the problem allows.

    COMPLEXITY:
    ──────────
    Time: O(n log k) — Each push/pop is log k
    Space: O(k) — Heap of size k
    """
    heap = []  # max-heap by storing (-distance, point)

    for x, y in points:
        dist = x * x + y * y
        heapq.heappush(heap, (-dist, [x, y]))
        if len(heap) > k:
            heapq.heappop(heap)

    return [point for _, point in heap]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Top K Frequent Words
# ════════════════════════════════════════════════════════════════════════

def top_k_frequent_words(words: List[str], k: int) -> List[str]:
    """
    QUESTION:
    ─────────
    Given an array of strings, return the k most frequent strings.
    Return sorted by frequency desc, then lexicographically asc.

    Example:
        Input: ["i","love","leetcode","i","love","coding"], k = 2
        Output: ["i", "love"]

    THOUGHT PROCESS:
    ────────────────
    1. Count frequencies with Counter
    2. Heapify all (-count, word) pairs — O(m) for m distinct words —
       then pop k times. The tuple order gives exactly the required
       ranking: higher count first, then lexicographically smaller word.
    3. Size-k min-heap variant (O(m log k), O(k) heap): the heap must
       evict the WORST item = lowest count, and on ties the
       lexicographically LARGER word. Strings can't be negated, so you
       need a wrapper class with a custom __lt__; then reverse at the end.
    4. Alternative: Bucket sort by frequency, sorting each bucket

    COMPLEXITY:
    ──────────
    Time: O(n + k log m) — Counting O(n), heapify O(m), k pops
    Space: O(m) — Counter + heap
    """
    from collections import Counter

    freq = Counter(words)
    # (-count, word): smallest tuple = highest count, then smallest word
    heap = [(-count, word) for word, count in freq.items()]
    heapq.heapify(heap)

    # Extract top k
    result = []
    for _ in range(k):
        result.append(heapq.heappop(heap)[1])

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Meeting Rooms II (Minimum Meeting Rooms)
# ════════════════════════════════════════════════════════════════════════

def min_meeting_rooms(intervals: List[List[int]]) -> int:
    """
    QUESTION:
    ─────────
    Given an array of meeting time intervals [start, end], find the
    minimum number of conference rooms required.

    Example:
        Input: [[0,30],[5,10],[15,20]]
        Output: 2

    THOUGHT PROCESS:
    ────────────────
    1. Sort meetings by start time
    2. Use a min-heap to track end times of meetings in progress
    3. For each meeting:
       - Remove meetings that have ended (end ≤ current start)
       - Add current meeting's end time
    4. The heap size at any point = number of rooms needed

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Sorting + heap operations
    Space: O(n) — Heap of meeting end times
    """
    if not intervals:
        return 0

    intervals.sort(key=lambda x: x[0])
    heap = [intervals[0][1]]  # Min-heap of end times

    for start, end in intervals[1:]:
        # If earliest ending meeting ends before this one starts
        if heap[0] <= start:
            heapq.heappop(heap)
        heapq.heappush(heap, end)

    return len(heap)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Maximum Profit in Job Scheduling (Heap + DP)
# ════════════════════════════════════════════════════════════════════════

def job_scheduling(start_time: List[int], end_time: List[int], profit: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given start, end, and profit arrays for jobs, find the maximum profit
    such that no two jobs overlap.

    Example:
        Input: startTime = [1,2,3,3], endTime = [3,4,5,6], profit = [50,10,40,70]
        Output: 120  ([1,3,50] + [3,6,70] = 120)

    THOUGHT PROCESS:
    ────────────────
    1. Sort jobs by start time
    2. Use a min-heap of (end_time, profit_earned_so_far)
    3. max_profit = best total of any chain that has ENDED by now
    4. For each job, pop every chain that ended at or before its start
       and fold it into max_profit (a job ending at t is compatible with
       one starting at t)
    5. Push current job with total profit = max_profit + current_profit
    6. Classic alternative: sort by END time; dp[i] = max(dp[i-1],
       profit[i] + dp[j]) where j = last job ending <= start[i], found by
       binary search. Same O(n log n). This is weighted interval
       scheduling — greedy (Greedy Q1) only works when all weights equal.

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Sorting + heap operations
    Space: O(n) — Heap
    """
    jobs = sorted(zip(start_time, end_time, profit), key=lambda x: x[0])
    heap = []  # (end_time, profit_earned_so_far)
    max_profit = 0

    for start, end, profit in jobs:
        # Pop all jobs that end before this one starts
        while heap and heap[0][0] <= start:
            max_profit = max(max_profit, heapq.heappop(heap)[1])

        # Push current job: profit = max_profit + current_profit
        heapq.heappush(heap, (end, max_profit + profit))

    # Process remaining jobs
    while heap:
        max_profit = max(max_profit, heapq.heappop(heap)[1])

    return max_profit


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Sliding Window Median
# ════════════════════════════════════════════════════════════════════════

def median_sliding_window(nums: List[int], k: int) -> List[float]:
    """
    QUESTION:
    ─────────
    Given an array of integers and a window size k, return the median
    of each sliding window.

    Example:
        Input: nums = [1,3,-1,-3,5,3,6,7], k = 3
        Output: [1.0, -1.0, -1.0, 3.0, 5.0, 6.0]

    THOUGHT PROCESS:
    ────────────────
    1. Two heaps: max-heap `small` (lower half) + min-heap `large` (upper
       half) — like MedianFinder (Q3).
    2. But we must REMOVE the element sliding out, and heapq can only
       remove the top. So: lazy deletion — leave the element in the heap
       and discard it when it surfaces at the top.
    3. The traps that make naive versions wrong:
       a) len(heap) counts dead entries, so keep separate counters of
          LIVE elements per side and balance on those
       b) After any pop/removal, prune dead entries off the top, so the
          tops we read are always live
       c) Duplicates: "delete one 5" is ambiguous if 5s sit in both
          heaps. Store (value, index) pairs instead — every entry is
          unique, and an entry is dead iff its index left the window.
    4. Which side is the outgoing element on? Compare its (value, index)
       with the live top of `small`: <= means it is in `small`.

    COMPLEXITY:
    ──────────
    Time: O(n log n) — each element pushed/popped O(1) times; heaps may
          hold dead entries, so sizes are O(n) not O(k) in the worst case
    Space: O(n) — Heaps including not-yet-pruned entries

    SIMPLER ALTERNATIVE:
    ────────────────────
    A sorted container (sortedcontainers.SortedList: O(log k) add/remove)
    or bisect.insort on a plain list (O(k) per step, O(n·k) total, often
    fast enough). Mention it; the two-heap version is what is probed.
    """
    small: List[Tuple[int, int]] = []   # max-heap of (-value, -index)
    large: List[Tuple[int, int]] = []   # min-heap of (value, index)
    small_live = large_live = 0
    lo = 0                              # Left edge of the window

    def prune() -> None:
        """Drop entries whose index has left the window from both tops."""
        while small and -small[0][1] < lo:
            heapq.heappop(small)
        while large and large[0][1] < lo:
            heapq.heappop(large)

    def small_top() -> Tuple[int, int]:
        return (-small[0][0], -small[0][1])

    def rebalance() -> None:
        nonlocal small_live, large_live
        while small_live > large_live + 1:            # small too big
            v, i = small_top()
            heapq.heappop(small)
            heapq.heappush(large, (v, i))
            small_live, large_live = small_live - 1, large_live + 1
            prune()
        while large_live > small_live:                # large too big
            v, i = heapq.heappop(large)
            heapq.heappush(small, (-v, -i))
            small_live, large_live = small_live + 1, large_live - 1
            prune()

    result = []
    for i, x in enumerate(nums):
        # 1) Add the incoming element to the correct half
        if small_live and (x, i) <= small_top():
            heapq.heappush(small, (-x, -i))
            small_live += 1
        else:
            heapq.heappush(large, (x, i))
            large_live += 1

        # 2) Retire the outgoing element (lazily)
        if i >= k:
            out = (nums[i - k], i - k)
            if out <= small_top():
                small_live -= 1
            else:
                large_live -= 1
            lo = i - k + 1
            prune()

        # 3) Restore the size invariant, then read the median
        rebalance()
        if i >= k - 1:
            if k % 2:
                result.append(float(small_top()[0]))
            else:
                result.append((small_top()[0] + large[0][0]) / 2.0)

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: Reorganize String (Task Scheduler variant)
# ════════════════════════════════════════════════════════════════════════

def reorganize_string(s: str) -> str:
    """
    QUESTION:
    ─────────
    Given a string s, rearrange its characters so that no two adjacent
    characters are the same. If impossible, return empty string.

    Example:
        Input: "aab"
        Output: "aba"
        Input: "aaab"
        Output: ""

    THOUGHT PROCESS:
    ────────────────
    1. Count frequencies, check if possible (max_freq ≤ (n+1)/2)
    2. Max-heap of (-freq, char)
    3. At each step, pop the most frequent remaining char and place it
    4. Hold it OUT of the heap for one round (prev_char / prev_count) and
       push it back only after the next char is placed — so the same char
       can never be popped twice in a row
    5. The feasibility check guarantees the heap is never empty while a
       held-back char still has copies left
    6. Generalises to "k distance apart": hold back chars in a queue for
       k rounds (Task Scheduler, Queues Q4)

    COMPLEXITY:
    ──────────
    Time: O(n log k) — k = unique chars (≤ 26)
    Space: O(k) — Heap and counter
    """
    from collections import Counter

    freq = Counter(s)
    n = len(s)

    # Check feasibility
    max_freq = max(freq.values())
    if max_freq > (n + 1) // 2:
        return ""

    # Max-heap of (-freq, char)
    heap = [(-cnt, char) for char, cnt in freq.items()]
    heapq.heapify(heap)

    result = []
    prev_char = None
    prev_count = 0

    while heap:
        cnt, char = heapq.heappop(heap)

        # If previous char still has count, push it back
        if prev_char and prev_count < 0:
            heapq.heappush(heap, (prev_count, prev_char))

        result.append(char)
        prev_char = char
        prev_count = cnt + 1  # cnt is negative, +1 moves toward zero

        # If still remaining, don't push back yet (avoid adjacent)
        # It will be pushed back in the next iteration

    return ''.join(result)


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("HEAPS — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Kth Largest in Stream")
    print("-" * 40)
    kth = KthLargest(3, [4, 5, 8, 2])
    print(f"   Initialize with [4,5,8,2], k=3")
    for val in [3, 5, 10, 9, 4]:
        print(f"   add({val}): {kth.add(val)}")

    # Q2
    print("\n2️⃣  Merge k Sorted Lists")
    print("-" * 40)
    # Helper to create linked list from list
    def to_list(arr):
        if not arr:
            return None
        head = ListNode(arr[0])
        curr = head
        for v in arr[1:]:
            curr.next = ListNode(v)
            curr = curr.next
        return head

    def to_pylist(node):
        result = []
        while node:
            result.append(node.val)
            node = node.next
        return result

    lists = [to_list([1, 4, 5]), to_list([1, 3, 4]), to_list([2, 6])]
    merged = merge_k_lists(lists)
    print(f"   Lists: [[1,4,5], [1,3,4], [2,6]]")
    print(f"   Merged: {to_pylist(merged)}")

    # Q3
    print("\n3️⃣  Find Median from Data Stream")
    print("-" * 40)
    mf = MedianFinder()
    for num in [1, 2, 3]:
        mf.add_num(num)
        print(f"   add({num}) → median: {mf.find_median()}")

    # Q4
    print("\n4️⃣  K Closest Points to Origin")
    print("-" * 40)
    points = [[1, 3], [-2, 2], [5, -1], [0, 1]]
    k = 2
    print(f"   Points: {points}, k={k}")
    print(f"   Closest: {k_closest(points, k)}")

    # Q5
    print("\n5️⃣  Top K Frequent Words")
    print("-" * 40)
    words = ["i", "love", "leetcode", "i", "love", "coding"]
    print(f"   Words: {words}, k=2")
    print(f"   Top: {top_k_frequent_words(words, 2)}")

    # Q6
    print("\n6️⃣  Meeting Rooms II")
    print("-" * 40)
    intervals = [[0, 30], [5, 10], [15, 20]]
    print(f"   Intervals: {intervals}")
    print(f"   Min rooms: {min_meeting_rooms(intervals)}")

    # Q7
    print("\n7️⃣  Maximum Profit in Job Scheduling")
    print("-" * 40)
    start = [1, 2, 3, 3]
    end = [3, 4, 5, 6]
    profit = [50, 10, 40, 70]
    print(f"   start={start}, end={end}, profit={profit}")
    print(f"   Max profit: {job_scheduling(start, end, profit)}")

    # Q8
    print("\n8️⃣  Sliding Window Median")
    print("-" * 40)
    nums = [1, 3, -1, -3, 5, 3, 6, 7]
    k = 3
    print(f"   nums={nums}, k={k}")
    print(f"   Medians: {median_sliding_window(nums, k)}")

    # Q9
    print("\n9️⃣  Reorganize String")
    print("-" * 40)
    for s in ["aab", "aaab"]:
        print(f"   \"{s}\" → \"{reorganize_string(s)}\"")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
