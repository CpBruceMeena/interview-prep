"""
QUEUES — Core Concepts & Interview Questions
=============================================

Core Concepts:
──────────────
• FIFO (First-In-First-Out) data structure
• Python collections.deque — O(1) pop from both ends
• Priority Queue (heapq) — elements ordered by priority
• Circular Queue — fixed-size buffer with wrap-around
• Monotonic Queue — sliding window maximum/minimum

Common Patterns:
────────────────
• BFS traversal (tree level-order, graph shortest path)
• Sliding Window Maximum (deque with monotonic decreasing order)
• Task scheduling / Producer-Consumer
• Implement Stack using Queue (and vice versa)
• Circular Buffer (ring buffer for streaming data)
"""

from typing import List, Optional
from collections import deque
import heapq


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Sliding Window Maximum
# ════════════════════════════════════════════════════════════════════════

def max_sliding_window(nums: List[int], k: int) -> List[int]:
    """
    QUESTION:
    ─────────
    Given an array and a sliding window of size k, find the maximum
    value in each window as it slides from left to right.

    Example:
        Input: nums = [1,3,-1,-3,5,3,6,7], k = 3
        Output: [3,3,5,5,6,7]

    THOUGHT PROCESS:
    ────────────────
    1. Brute Force: For each window, scan k elements — O(n·k)
    2. Deque (Monotonic Queue) Approach:
       - Maintain a deque of indices with DESCENDING values
       - The front of deque is always the max of current window
       - When window slides:
         a) Remove indices that are out of window (left side)
         b) Remove indices whose values are ≤ new element (they're useless)
         c) Add new element's index
    3. Why remove smaller values? If a new element is larger than older
       elements in the window, those older elements can never be max
       for any remaining window (since the new element is both larger
       and will stay longer)
    4. Store INDICES, not values: the index tells us when the front has
       slid out of the window, and duplicates stay distinguishable.

    COMPLEXITY:
    ──────────
    Time: O(n) — Each element added and removed from deque at most once
    Space: O(k) — Deque stores at most k elements
    """
    if not nums or k == 0:
        return []

    result = []
    dq = deque()  # indices with decreasing values

    for i in range(len(nums)):
        # Remove indices outside current window
        if dq and dq[0] < i - k + 1:
            dq.popleft()

        # Remove indices whose values are ≤ current value
        while dq and nums[dq[-1]] <= nums[i]:
            dq.pop()

        dq.append(i)

        # Add to result when window is fully formed
        if i >= k - 1:
            result.append(nums[dq[0]])

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Implement Queue using Stacks
# ════════════════════════════════════════════════════════════════════════

class QueueUsingStacks:
    """
    QUESTION:
    ─────────
    Implement a FIFO queue using only two stacks.

    THOUGHT PROCESS:
    ────────────────
    1. Two stacks: "input" for push, "output" for pop/peek
    2. On push: just push to input stack (O(1))
    3. On pop/peek: if output is empty, transfer everything from input
       to output (reverses order → now FIFO)
    4. Amortized O(1) for all operations:
       - Each element is moved at most once from input to output
       - The transfer reverses the stack order to get FIFO

    COMPLEXITY:
    ──────────
    Push: O(1) amortized
    Pop/Peek: O(1) amortized (O(n) worst-case when output is empty)
    Space: O(n) — Two stacks store all elements
    """

    def __init__(self):
        self._input = []
        self._output = []

    def push(self, x: int) -> None:
        self._input.append(x)

    def pop(self) -> Optional[int]:
        self._transfer()
        return self._output.pop() if self._output else None

    def peek(self) -> Optional[int]:
        self._transfer()
        return self._output[-1] if self._output else None

    def empty(self) -> bool:
        return not self._input and not self._output

    def _transfer(self) -> None:
        """Move all elements from input to output (reverses order)."""
        if not self._output:
            while self._input:
                self._output.append(self._input.pop())


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Design Circular Queue
# ════════════════════════════════════════════════════════════════════════

class CircularQueue:
    """
    QUESTION:
    ─────────
    Design a circular queue (ring buffer) with fixed size.
    Supports enQueue, deQueue, Front, Rear, isEmpty, isFull.

    THOUGHT PROCESS:
    ────────────────
    1. Array-based with front and rear pointers
    2. Circular indexing: (index + 1) % capacity
    3. The hard part is telling "empty" from "full", because in both
       cases the pointers can line up. Three standard fixes:
       a) Keep a size counter (used here: full ⇔ size == capacity)
       b) Sentinel: front == -1 means empty (also used here)
       c) Waste one slot: full ⇔ (rear + 1) % capacity == front
    4. Wrap-around eliminates the need to shift elements
    5. Production ring buffers (e.g. LMAX Disruptor) use a power-of-two
       capacity so `% capacity` becomes `& (capacity - 1)`

    COMPLEXITY:
    ──────────
    Time: O(1) — All operations are O(1)
    Space: O(k) — Fixed-size array
    """

    def __init__(self, k: int):
        self._buffer = [0] * k
        self._capacity = k
        self._front = -1
        self._rear = -1
        self._size = 0

    def enqueue(self, value: int) -> bool:
        if self.is_full():
            return False
        if self.is_empty():
            self._front = 0
        self._rear = (self._rear + 1) % self._capacity
        self._buffer[self._rear] = value
        self._size += 1
        return True

    def dequeue(self) -> bool:
        if self.is_empty():
            return False
        if self._front == self._rear:
            # Queue becomes empty
            self._front = -1
            self._rear = -1
        else:
            self._front = (self._front + 1) % self._capacity
        self._size -= 1
        return True

    def front(self) -> int:
        return -1 if self.is_empty() else self._buffer[self._front]

    def rear(self) -> int:
        return -1 if self.is_empty() else self._buffer[self._rear]

    def is_empty(self) -> bool:
        return self._front == -1

    def is_full(self) -> bool:
        return self._size == self._capacity


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Task Scheduler
# ════════════════════════════════════════════════════════════════════════

def least_interval(tasks: List[str], n: int) -> int:
    """
    QUESTION:
    ─────────
    Given CPU tasks represented by letters and a cooling interval n,
    find the minimum time to complete all tasks. Same tasks must be
    at least n intervals apart.

    Example:
        Input: tasks = ["A","A","A","B","B","B"], n = 2
        Output: 8  (A → B → idle → A → B → idle → A → B)

    THOUGHT PROCESS:
    ────────────────
    1. Max-heap + Queue pattern (simulation, implemented below):
       - Count frequencies, push to max-heap
       - Schedule the highest frequency task available
       - After scheduling, task goes to "cooling queue" with cooldown time
    2. Formula approach (exact, and the expected optimal answer):
       - max_freq = highest count, num_max = how many tasks have it
       - Frame: (max_freq - 1) full blocks of length n + 1, plus a last
         block holding the num_max most frequent tasks
         → (max_freq - 1) * (n + 1) + num_max
       - If there are more tasks than idle slots, no idling is needed
         and the answer is just len(tasks)
       - answer = max(len(tasks), (max_freq - 1) * (n + 1) + num_max)
    3. The simulation generalises (e.g. return the actual schedule); the
       formula is O(m) and is what interviewers usually want to see.
       Greedy Q9 implements the formula.

    COMPLEXITY:
    ──────────
    Time: O(T log 26) = O(T) — T = the answer (one loop iteration per
          time unit, idle units included); T ≤ m·(n + 1)
    Space: O(1) — At most 26 unique tasks
    """
    from collections import Counter

    freq = Counter(tasks)
    max_heap = [-count for count in freq.values()]
    heapq.heapify(max_heap)

    time = 0
    cooling = deque()  # (remaining_count, available_at_time)

    while max_heap or cooling:
        time += 1

        if max_heap:
            count = -heapq.heappop(max_heap)
            count -= 1
            if count > 0:
                cooling.append((count, time + n))
        # else: idle time

        # Move tasks from cooling back to heap when ready
        if cooling and cooling[0][1] == time:
            count, _ = cooling.popleft()
            heapq.heappush(max_heap, -count)

    return time


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Implement Stack using Queues
# ════════════════════════════════════════════════════════════════════════

class StackUsingQueues:
    """
    QUESTION:
    ─────────
    Implement LIFO stack using two FIFO queues.

    THOUGHT PROCESS:
    ────────────────
    1. Use two queues: primary and secondary
    2. On push: enqueue to secondary, then move all from primary to secondary
       → this puts the new element at the front of the queue order
       → then swap primary and secondary
    3. Alternative: push to primary, on pop/peek transfer all except last
    4. The key is to reverse the order: new element must become the
       next to be dequeued (LIFO requires most recent first)

    COMPLEXITY:
    ──────────
    Push: O(n) — Need to rotate elements
    Pop/Peek: O(1) — Front of queue is top of stack
    Space: O(n) — Two queues
    """

    def __init__(self):
        self._primary = deque()
        self._secondary = deque()

    def push(self, x: int) -> None:
        # New element goes to secondary
        self._secondary.append(x)
        # Move all from primary to secondary (reverses order)
        while self._primary:
            self._secondary.append(self._primary.popleft())
        # Swap
        self._primary, self._secondary = self._secondary, self._primary

    def pop(self) -> Optional[int]:
        return self._primary.popleft() if self._primary else None

    def top(self) -> Optional[int]:
        return self._primary[0] if self._primary else None

    def empty(self) -> bool:
        return not self._primary


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Reorder Data in Log Files
# ════════════════════════════════════════════════════════════════════════

def reorder_log_files(logs: List[str]) -> List[str]:
    """
    QUESTION:
    ─────────
    You have an array of logs. Each log is space-delimited with the first
    word being the identifier. Letter-logs come before digit-logs.
    Letter-logs are sorted lexicographically (by content, then by id).
    Digit-logs maintain their original order.

    Example:
        Input: logs = ["dig1 8 1 5 1","let1 art can","dig2 3 6",
                       "let2 own kit dig","let3 art zero"]
        Output: ["let1 art can","let3 art zero","let2 own kit dig",
                 "dig1 8 1 5 1","dig2 3 6"]

    THOUGHT PROCESS:
    ────────────────
    1. Classify logs into letter-logs and digit-logs
    2. Sort letter-logs by (content, identifier) using custom key
    3. Digit-logs stay in original order (stable sort)
    4. Concatenate: sorted letter-logs + digit-logs

    COMPLEXITY:
    ──────────
    Time: O(m·L·log m) — sorting m letter-logs; each string comparison
          costs up to O(L) for log length L
    Space: O(m·L) — Sort keys and the result
    """
    letter_logs = []
    digit_logs = []

    for log in logs:
        # Split only on first space: identifier = parts[0], rest = parts[1:]
        parts = log.split(' ', 1)
        if parts[1][0].isdigit():
            digit_logs.append(log)
        else:
            letter_logs.append(log)

    # Sort letter-logs: by content first, then by identifier
    letter_logs.sort(key=lambda x: (x.split(' ', 1)[1], x.split(' ', 1)[0]))

    return letter_logs + digit_logs


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Rotting Oranges (Multi-Source BFS)
# ════════════════════════════════════════════════════════════════════════

def oranges_rotting(grid: List[List[int]]) -> int:
    """
    QUESTION:
    ─────────
    In a grid, 0 = empty, 1 = fresh orange, 2 = rotten orange. Every
    minute, each fresh orange 4-directionally adjacent to a rotten one
    becomes rotten. Return the minutes until no fresh orange remains, or
    -1 if that is impossible.

    Example:
        Input: [[2,1,1],[1,1,0],[0,1,1]]
        Output: 4

    THOUGHT PROCESS:
    ────────────────
    1. Running BFS from each rotten orange separately and taking minima
       is O((R·C)²).
    2. Multi-source BFS: seed the queue with ALL rotten oranges at once
       (distance 0). BFS then expands level by level, and each level is
       one minute. The first time a fresh cell is reached is the earliest
       it can rot, because BFS visits cells in order of distance.
    3. Count fresh oranges up front; decrement as they rot. If any remain
       when the queue empties, some orange is unreachable → -1.
    4. Same pattern: "walls and gates", "01 matrix", nearest exit, the
       distance from every cell to its nearest source.

    COMPLEXITY:
    ──────────
    Time: O(R·C) — Each cell enters the queue at most once
    Space: O(R·C) — Queue in the worst case

    EDGE CASES:
    ──────────
    • No fresh oranges at all → 0 (even if there are no rotten ones)
    • Fresh oranges but no rotten ones → -1
    • Mark a cell rotten when it is ENQUEUED, not when dequeued,
      otherwise it can be enqueued twice
    """
    rows, cols = len(grid), len(grid[0]) if grid else 0
    queue = deque()
    fresh = 0

    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == 2:
                queue.append((r, c))
            elif grid[r][c] == 1:
                fresh += 1

    minutes = 0
    while queue and fresh:
        minutes += 1
        for _ in range(len(queue)):          # Process one full level
            r, c = queue.popleft()
            for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nr, nc = r + dr, c + dc
                if 0 <= nr < rows and 0 <= nc < cols and grid[nr][nc] == 1:
                    grid[nr][nc] = 2         # Mark on enqueue
                    fresh -= 1
                    queue.append((nr, nc))

    return minutes if fresh == 0 else -1


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("QUEUES — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Sliding Window Maximum")
    print("-" * 40)
    nums = [1, 3, -1, -3, 5, 3, 6, 7]
    k = 3
    print(f"   Input: nums={nums}, k={k}")
    print(f"   Output: {max_sliding_window(nums, k)}")

    # Q2
    print("\n2️⃣  Queue using Stacks")
    print("-" * 40)
    q = QueueUsingStacks()
    q.push(1)
    q.push(2)
    print(f"   push(1), push(2)")
    print(f"   peek(): {q.peek()}")
    print(f"   pop(): {q.pop()}")
    print(f"   empty(): {q.empty()}")

    # Q3
    print("\n3️⃣  Circular Queue")
    print("-" * 40)
    cq = CircularQueue(3)
    print(f"   enqueue(1): {cq.enqueue(1)}")
    print(f"   enqueue(2): {cq.enqueue(2)}")
    print(f"   enqueue(3): {cq.enqueue(3)}")
    print(f"   enqueue(4) (full): {cq.enqueue(4)}")
    print(f"   rear(): {cq.rear()}")
    print(f"   dequeue(): {cq.dequeue()}")
    print(f"   enqueue(4): {cq.enqueue(4)}")
    print(f"   rear(): {cq.rear()}")

    # Q4
    print("\n4️⃣  Task Scheduler")
    print("-" * 40)
    tasks = ["A", "A", "A", "B", "B", "B"]
    n = 2
    print(f"   tasks={tasks}, n={n}")
    print(f"   min time: {least_interval(tasks, n)}")

    # Q5
    print("\n5️⃣  Stack using Queues")
    print("-" * 40)
    st = StackUsingQueues()
    for x in (1, 2, 3):
        st.push(x)
    print(f"   push(1), push(2), push(3)")
    print(f"   top(): {st.top()}")
    print(f"   pop(): {st.pop()}")
    print(f"   top() after pop: {st.top()}")

    # Q6
    print("\n6️⃣  Reorder Log Files")
    print("-" * 40)
    logs = ["dig1 8 1 5 1", "let1 art can", "dig2 3 6",
            "let2 own kit dig", "let3 art zero"]
    print(f"   Input: {logs}")
    print(f"   Output: {reorder_log_files(logs)}")

    # Q7
    print("\n7️⃣  Rotting Oranges (Multi-Source BFS)")
    print("-" * 40)
    grid = [[2, 1, 1], [1, 1, 0], [0, 1, 1]]
    print(f"   Input: {grid}")
    print(f"   Minutes: {oranges_rotting([row[:] for row in grid])}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
