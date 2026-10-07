"""
GREEDY ALGORITHMS — Core Concepts & Interview Questions
========================================================

Core Concepts:
──────────────
• Greedy choice property: A global optimum can be reached by making
  the locally optimal choice at each step
• Optimal substructure: An optimal solution contains optimal solutions
  to subproblems
• Unlike DP: Greedy doesn't explore all possibilities — it commits
  to the best immediate choice

When Greedy Works:
──────────────────
• Activity Selection: Earliest finish time first
• Huffman Coding: Merge two smallest frequencies
• Dijkstra: Process node with smallest distance
• Prim's / Kruskal's: Take smallest edge that doesn't create cycle
• Fractional Knapsack: Take highest value/weight ratio

When Greedy Fails:
──────────────────
• 0/1 Knapsack: Greedy ratio fails — needs DP
• Longest simple path: always taking the longest next edge can walk
  into a dead end; the problem is NP-hard in general (linear-time DP
  only on DAGs)
• Coin Change (some denominations): greedy fails for non-canonical coins
  — [1, 3, 4] to make 6: greedy 4+1+1, optimal 3+3
• Weighted interval scheduling: earliest-finish fails once intervals
  carry different values (DP + binary search: Heaps Q7)

How to tell in an interview:
• Try to break your greedy rule with a 3-4 element counterexample
  before coding it. If you can't, sketch the exchange argument.

Proof Techniques:
─────────────────
• Exchange argument: Show any optimal solution can be transformed
  to greedy solution without worsening
• Greedy stays ahead: Show greedy is at least as good as any other
  solution at each step
"""

from typing import List, Optional, Tuple
from collections import Counter
import heapq


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Activity Selection (Earliest Finish First)
# ════════════════════════════════════════════════════════════════════════

def activity_selection(start: List[int], end: List[int]) -> List[int]:
    """
    QUESTION:
    ─────────
    Given start and end times of activities, select the maximum number
    of non-overlapping activities.

    Example:
        Input: start = [1, 3, 0, 5, 8, 5], end = [2, 4, 6, 7, 9, 9]
        Output: [0, 1, 3, 4]  (indices of selected activities)

    THOUGHT PROCESS:
    ────────────────
    1. Sort by finish time (earliest finish first)
    2. Pick first activity (earliest finish)
    3. For each remaining activity:
       - If its start ≥ last_finish_time, select it
    4. Proof (exchange argument): take any optimal schedule and replace
       its first activity with the earliest-finishing one. It ends no
       later, so nothing after it conflicts → still optimal. Repeat on
       the remaining activities.
    5. Sorting by START time or by DURATION fails: e.g. one long early
       activity blocks several short ones.

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Sorting by finish time
    Space: O(n) — For sorted activities
    """
    n = len(start)
    # Pair activities with their original indices
    activities = list(zip(start, end, range(n)))
    # Sort by end time (and by start time for tie-breaking)
    activities.sort(key=lambda x: (x[1], x[0]))

    selected = []
    last_finish = float('-inf')   # Not -1: start times may be negative

    for s, e, idx in activities:
        if s >= last_finish:
            selected.append(idx)
            last_finish = e

    return selected


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Huffman Coding (Greedy Prefix-Free Compression)
# ════════════════════════════════════════════════════════════════════════


class HuffmanNode:
    """Node for Huffman Tree."""
    def __init__(self, char: str, freq: int):
        self.char = char
        self.freq = freq
        self.left: Optional['HuffmanNode'] = None
        self.right: Optional['HuffmanNode'] = None

    def __lt__(self, other):
        return self.freq < other.freq


def huffman_encode(text: str) -> Tuple[dict, str]:
    """
    QUESTION:
    ─────────
    Build a Huffman coding tree and encode a string.
    Return the character-to-code mapping and the encoded binary string.

    Example:
        Input: "AAAAABBBCCD"
        Output: codes and encoded string

    THOUGHT PROCESS:
    ────────────────
    1. Count character frequencies
    2. Build a min-heap of (freq, node)
    3. While heap has >1 node, merge two smallest:
       - Create parent node with freq = sum
       - Parent has no char (internal node)
       - Two smallest become children
    4. Assign codes: Left = '0', Right = '1'
    5. Greedy choice: Merging smallest frequencies ensures optimal
       prefix-free code (minimum weighted path length)
    6. Proof sketch (exchange argument): in some optimal tree the two
       least frequent symbols are siblings at the deepest level — if a
       more frequent symbol sat deeper, swapping it with a rarer one
       could only lower the cost. Merge them into one symbol and repeat.
    7. Prefix-free (no code is a prefix of another) is what makes the
       bit string decodable without separators: every symbol is a leaf.
    8. Edge case: a single distinct symbol gets code '0' (a 1-node tree
       would otherwise give it the empty code).

    COMPLEXITY:
    ──────────
    Time: O(n + m log m) — count n chars, then m - 1 heap merges
          (m unique chars)
    Space: O(m) — Tree size
    """
    if not text:
        return {}, ""

    freq = Counter(text)

    # Build heap
    heap = [HuffmanNode(char, f) for char, f in freq.items()]
    heapq.heapify(heap)

    # Build Huffman Tree
    while len(heap) > 1:
        left = heapq.heappop(heap)
        right = heapq.heappop(heap)
        parent = HuffmanNode('', left.freq + right.freq)
        parent.left = left
        parent.right = right
        heapq.heappush(heap, parent)

    # Generate codes
    codes = {}

    def generate_codes(node: Optional[HuffmanNode], code: str) -> None:
        if not node:
            return
        if node.char:  # Leaf node
            codes[node.char] = code if code else '0'
            return
        generate_codes(node.left, code + '0')
        generate_codes(node.right, code + '1')

    generate_codes(heap[0], '')

    # Encode text
    encoded = ''.join(codes[ch] for ch in text)

    return codes, encoded


def huffman_decode(codes: dict, encoded: str) -> str:
    """Decode a Huffman-encoded string. Reverse mapping."""
    if not codes or not encoded:
        return ""
    reverse_codes = {v: k for k, v in codes.items()}

    result = []
    current = ""
    for bit in encoded:
        current += bit
        if current in reverse_codes:
            result.append(reverse_codes[current])
            current = ""

    return ''.join(result)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Jump Game II (Minimum Jumps to Reach End)
# ════════════════════════════════════════════════════════════════════════

def jump(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given an array where nums[i] is the max jump length from position i,
    return the minimum number of jumps to reach the last index.

    Example:
        Input: [2, 3, 1, 1, 4]
        Output: 2  (2 → 3 → 4)

    THOUGHT PROCESS:
    ────────────────
    1. At each position, we can jump within [i, i + nums[i]]
    2. Greedy approach: Track the farthest reachable position
    3. When we reach the end of the current jump's range, we must
       take a jump (increment jumps counter)
    4. Set new range boundary to farthest reachable so far
    5. Equivalent view: BFS where "level j" = all indices reachable in
       exactly j jumps; each level is a contiguous range, so we only
       track its right end. That is why it's O(n), not O(n²) like DP.
    6. Assumes the end is reachable (the problem guarantees it). For
       Jump Game I (can we reach?), just check i <= farthest at every i.

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass
    Space: O(1) — Only variables
    """
    n = len(nums)
    if n <= 1:
        return 0

    jumps = 0
    current_end = 0  # End of current jump range
    farthest = 0     # Farthest we can reach

    for i in range(n - 1):
        farthest = max(farthest, i + nums[i])

        # If we've reached the end of current range, take a jump
        if i == current_end:
            jumps += 1
            current_end = farthest

            if current_end >= n - 1:
                break

    return jumps


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Gas Station (Circular Tour)
# ════════════════════════════════════════════════════════════════════════

def can_complete_circuit(gas: List[int], cost: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given circular gas stations, each with gas[i] and cost to reach next,
    find the starting station to complete the circuit, or -1.

    Example:
        Input: gas = [1,2,3,4,5], cost = [3,4,5,1,2]
        Output: 3

    THOUGHT PROCESS:
    ────────────────
    1. If total gas < total cost, impossible → return -1
    2. At each position, track current tank balance
    3. If balance < 0, this starting point fails; try next station
    4. The key insight: if starting at s we run dry at station k, every
       start between s and k also runs dry by k — each of them arrives
       at k with no more fuel than we had (we reached them with a
       non-negative tank). So jump straight to k + 1.
    5. Why total >= 0 guarantees the final candidate works: the deficit
       before `start` is covered by the surplus from `start` to the end.
       (Several starts can work in general, e.g. all-zero inputs;
       LeetCode guarantees a unique answer, and this returns the first.)

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass
    Space: O(1) — Only variables
    """
    if sum(gas) < sum(cost):
        return -1

    total = 0
    start = 0

    for i in range(len(gas)):
        total += gas[i] - cost[i]
        if total < 0:
            # Can't start from current start; try next station
            total = 0
            start = i + 1

    return start


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Partition Labels
# ════════════════════════════════════════════════════════════════════════

def partition_labels(s: str) -> List[int]:
    """
    QUESTION:
    ─────────
    Partition a string into as many parts as possible such that each
    character appears in at most one part. Return the sizes of each part.

    Example:
        Input: "ababcbacadefegdehijhklij"
        Output: [9, 7, 8]
        ("ababcbaca", "defegde", "hijhklij")

    THOUGHT PROCESS:
    ────────────────
    1. Record the LAST occurrence of each character
    2. Iterate, tracking the farthest last occurrence seen so far
    3. When current index == farthest, the current partition ends
    4. Greedy: We extend the partition as far as needed to include
       all occurrences of characters seen so far

    COMPLEXITY:
    ──────────
    Time: O(n) — Two passes
    Space: O(1) — At most 26 characters
    """
    # Last occurrence of each character
    last = {char: i for i, char in enumerate(s)}

    result = []
    start = 0
    farthest = 0

    for i, char in enumerate(s):
        farthest = max(farthest, last[char])
        if i == farthest:
            result.append(i - start + 1)
            start = i + 1

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Maximum Units on a Truck (Fractional/0-1 Greedy)
# ════════════════════════════════════════════════════════════════════════

def maximum_units(box_types: List[List[int]], truck_size: int) -> int:
    """
    QUESTION:
    ─────────
    Given box types where boxTypes[i] = [num_boxes, units_per_box],
    and a truck that can carry truckSize boxes, maximize total units.

    Example:
        Input: boxTypes = [[1,3],[2,2],[3,1]], truckSize = 4
        Output: 8  (1×3 + 2×2 + 1×1 = 8)

    THOUGHT PROCESS:
    ────────────────
    1. Sort by units per box descending
    2. Take as many boxes as possible from the highest-unit type
    3. This is greedy: local optimum (most units per box) leads to
       global optimum
    4. Why greedy is safe here but not for 0/1 knapsack: every box costs
       the same capacity (1 slot), so units-per-box is also value per
       unit of capacity and any box can be swapped for a better one.
       With different weights you need DP.

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Sorting
    Space: O(1) — In-place sort
    """
    box_types.sort(key=lambda x: -x[1])  # Sort by units per box descending
    total_units = 0

    for boxes, units in box_types:
        take = min(boxes, truck_size)
        total_units += take * units
        truck_size -= take
        if truck_size == 0:
            break

    return total_units


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Non-Overlapping Intervals (Min Removals)
# ════════════════════════════════════════════════════════════════════════

def erase_overlap_intervals(intervals: List[List[int]]) -> int:
    """
    QUESTION:
    ─────────
    Given an array of intervals, find the minimum number of intervals
    to remove to make the rest non-overlapping.

    Example:
        Input: [[1,2],[2,3],[3,4],[1,3]]
        Output: 1  (remove [1,3])

    THOUGHT PROCESS:
    ────────────────
    1. Sort by end time (earliest finish first — same as activity selection)
    2. Keep intervals that don't overlap with the last kept one
    3. Count removed intervals
    4. Greedy choice: Keeping the earliest-finishing interval leaves
       the most room for subsequent intervals

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Sorting
    Space: O(1) — In-place sort
    """
    if not intervals:
        return 0

    intervals.sort(key=lambda x: x[1])
    count = 0
    last_end = intervals[0][1]

    for start, end in intervals[1:]:
        if start < last_end:
            count += 1  # Remove this interval
        else:
            last_end = end  # Keep this interval

    return count


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Candy Distribution (Minimum Candies)
# ════════════════════════════════════════════════════════════════════════

def candy(ratings: List[int]) -> int:
    """
    QUESTION:
    ─────────
    There are n children with ratings. Each child must get at least
    1 candy. Children with a higher rating get more candies than
    their neighbors. Find the minimum candies needed.

    Example:
        Input: [1, 0, 2]
        Output: 5  (2, 1, 2)

    THOUGHT PROCESS:
    ────────────────
    1. Two-pass greedy:
       - Left-to-right: If rating[i] > rating[i-1], give 1 more than left
       - Right-to-left: If rating[i] > rating[i+1], take max(current, right+1)
    2. The two passes ensure both neighbor constraints are satisfied
    3. Taking max() in the second pass keeps the left-neighbour rule
       satisfied while fixing the right-neighbour rule
    4. Equal ratings impose no constraint: [1, 2, 2] → 1, 2, 1
    5. O(1)-space variant exists (count up/down slopes) — mention only

    COMPLEXITY:
    ──────────
    Time: O(n) — Two passes
    Space: O(n) — Candies array
    """
    n = len(ratings)
    candies = [1] * n

    # Left to right: ensure higher rating than left neighbor
    for i in range(1, n):
        if ratings[i] > ratings[i - 1]:
            candies[i] = candies[i - 1] + 1

    # Right to left: ensure higher rating than right neighbor
    for i in range(n - 2, -1, -1):
        if ratings[i] > ratings[i + 1]:
            candies[i] = max(candies[i], candies[i + 1] + 1)

    return sum(candies)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: Task Scheduler (Min Interval)
# ════════════════════════════════════════════════════════════════════════

def least_interval_greedy(tasks: List[str], n: int) -> int:
    """
    QUESTION:
    ─────────
    Given CPU tasks (letters) and cooldown n, find minimum time.
    Same tasks must be n apart.

    Example:
        Input: tasks = ["A","A","A","B","B","B"], n = 2
        Output: 8  (A→B→idle→A→B→idle→A→B)

    THOUGHT PROCESS:
    ────────────────
    1. The most frequent task determines the minimum framework
    2. Formula: (max_freq - 1) * (n + 1) + count_max_freq
    3. If there are many unique tasks filling idle slots, the answer
       is just len(tasks) (no idle needed)
    4. Greedy: Schedule the most frequent task first, then fill
       idle slots with other tasks
    5. Same problem simulated with a heap + cooldown queue: Queues Q4

    COMPLEXITY:
    ──────────
    Time: O(m) — m = number of tasks: count frequencies + formula
          (n here is the cooldown, not the input size)
    Space: O(1) — At most 26 counters
    """
    from collections import Counter
    freq = Counter(tasks)
    max_freq = max(freq.values())
    max_count = sum(1 for f in freq.values() if f == max_freq)

    # Formula-based approach (mathematically proven greedy)
    result = (max_freq - 1) * (n + 1) + max_count
    return max(result, len(tasks))


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("GREEDY ALGORITHMS — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Activity Selection")
    print("-" * 40)
    start = [1, 3, 0, 5, 8, 5]
    end = [2, 4, 6, 7, 9, 9]
    sel = activity_selection(start, end)
    print(f"   Activities: {list(zip(start, end))}")
    print(f"   Selected indices: {sel}")
    print(f"   Selected activities: {[(start[i], end[i]) for i in sel]}")

    # Q2
    print("\n2️⃣  Huffman Coding")
    print("-" * 40)
    text = "AAAAABBBCCD"
    codes, encoded = huffman_encode(text)
    decoded = huffman_decode(codes, encoded)
    print(f"   Text: \"{text}\"")
    print(f"   Codes: {codes}")
    print(f"   Encoded: {encoded}")
    print(f"   Decoded: \"{decoded}\"")
    print(f"   Compression ratio: {len(text)*8} bits → {len(encoded)} bits")

    # Q3
    print("\n3️⃣  Jump Game II")
    print("-" * 40)
    nums = [2, 3, 1, 1, 4]
    print(f"   Input: {nums}")
    print(f"   Min jumps: {jump(nums)}")

    # Q4
    print("\n4️⃣  Gas Station")
    print("-" * 40)
    gas, cost = [1, 2, 3, 4, 5], [3, 4, 5, 1, 2]
    print(f"   gas={gas}, cost={cost}")
    print(f"   Start station: {can_complete_circuit(gas, cost)}")

    # Q5
    print("\n5️⃣  Partition Labels")
    print("-" * 40)
    s = "ababcbacadefegdehijhklij"
    print(f"   Input: \"{s}\"")
    print(f"   Partition sizes: {partition_labels(s)}")

    # Q6
    print("\n6️⃣  Maximum Units on Truck")
    print("-" * 40)
    box_types = [[1, 3], [2, 2], [3, 1]]
    truck_size = 4
    print(f"   Box types: {box_types}, truck size: {truck_size}")
    print(f"   Max units: {maximum_units(box_types, truck_size)}")

    # Q7
    print("\n7️⃣  Non-Overlapping Intervals")
    print("-" * 40)
    intervals = [[1, 2], [2, 3], [3, 4], [1, 3]]
    print(f"   Intervals: {intervals}")
    print(f"   Min removals: {erase_overlap_intervals(intervals)}")

    # Q8
    print("\n8️⃣  Candy Distribution")
    print("-" * 40)
    ratings = [1, 0, 2]
    print(f"   Ratings: {ratings}")
    print(f"   Min candies: {candy(ratings)}")

    # Q9
    print("\n9️⃣  Task Scheduler")
    print("-" * 40)
    tasks = ["A", "A", "A", "B", "B", "B"]
    n = 2
    print(f"   Tasks: {tasks}, cooldown={n}")
    print(f"   Min time: {least_interval_greedy(tasks, n)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
