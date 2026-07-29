"""
STACKS — Core Concepts & Interview Questions
=============================================

Core Concepts:
──────────────
• LIFO (Last-In-First-Out) data structure
• Python list can be used as a stack: append() for push, pop() for pop
• Undo/Redo operations, expression evaluation, backtracking
• Monotonic Stack pattern — maintaining sorted order in the stack
• Stack-based DFS for tree/graph traversals

Common Patterns:
────────────────
• Next Greater Element (monotonic decreasing stack)
• Expression evaluation (two-stack algorithm: numbers + operators)
• Parentheses validation
• Min stack (track minimum with each element)
• Histogram area (largest rectangle)
"""

from typing import List, Optional, Tuple


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Valid Parentheses
# ════════════════════════════════════════════════════════════════════════

def is_valid_parentheses(s: str) -> bool:
    """
    QUESTION:
    ─────────
    Given a string s containing '(', ')', '{', '}', '[', ']', determine
    if the input string is valid. Open brackets must be closed in the
    correct order.

    Example:
        Input: "()[]{}"
        Output: true
        Input: "([)]"
        Output: false

    THOUGHT PROCESS:
    ────────────────
    1. Use stack to track opening brackets
    2. When we see a closing bracket, check if it matches the top of stack
    3. If stack is empty when seeing a closing bracket → invalid
    4. If stack is not empty at end → invalid (unclosed brackets)
    5. Key: Map closing to opening for O(1) matching check

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass through the string
    Space: O(n) — Stack can hold up to n opening brackets
    """
    matching = {')': '(', '}': '{', ']': '['}
    stack = []

    for char in s:
        if char in matching:
            # Closing bracket — must match top of stack
            if not stack or stack[-1] != matching[char]:
                return False
            stack.pop()
        else:
            # Opening bracket — push to stack
            stack.append(char)

    return len(stack) == 0


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Min Stack
# ════════════════════════════════════════════════════════════════════════

class MinStack:
    """
    QUESTION:
    ─────────
    Design a stack that supports push, pop, top, and retrieving the
    minimum element in O(1) time.

    Example:
        MinStack minStack = new MinStack()
        minStack.push(-2)
        minStack.push(0)
        minStack.push(-3)
        minStack.getMin() → -3
        minStack.pop()
        minStack.top() → 0
        minStack.getMin() → -2

    THOUGHT PROCESS:
    ────────────────
    1. Naive: Scan entire stack for min on getMin() — O(n)
    2. Better: Store (value, current_min) pairs in stack
       - Push: new_min = min(value, current_min)
       - Pop: Just pop, min is restored automatically
       - This works because each element carries the min at that point
    3. Space-optimized: Use a separate min stack
       - Only push to min stack when new_min changes
       - Only pop from min stack when top equals current_min
       - Saves space when min doesn't change frequently

    COMPLEXITY:
    ──────────
    Time: O(1) — All operations are O(1)
    Space: O(n) — Stack stores n elements with their min values
    """

    def __init__(self):
        self._stack = []  # (value, min_at_this_point)

    def push(self, val: int) -> None:
        current_min = self.get_min()
        new_min = min(val, current_min) if current_min is not None else val
        self._stack.append((val, new_min))

    def pop(self) -> None:
        if self._stack:
            self._stack.pop()

    def top(self) -> Optional[int]:
        if self._stack:
            return self._stack[-1][0]
        return None

    def get_min(self) -> Optional[int]:
        if self._stack:
            return self._stack[-1][1]
        return None


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Daily Temperatures (Next Greater Element)
# ════════════════════════════════════════════════════════════════════════

def daily_temperatures(temperatures: List[int]) -> List[int]:
    """
    QUESTION:
    ─────────
    Given an array of daily temperatures, return an array answer such that
    answer[i] is the number of days until a warmer temperature. If no
    warmer day exists, answer[i] = 0.

    Example:
        Input: [73, 74, 75, 71, 69, 72, 76, 73]
        Output: [1, 1, 4, 2, 1, 1, 0, 0]

    THOUGHT PROCESS:
    ────────────────
    1. Brute Force: For each day, scan forward for warmer — O(n²)
    2. Monotonic Decreasing Stack:
       - Stack stores indices (not values) with decreasing temperatures
       - When we see a temp > stack top's temp → we've found the answer
         for the stack top index
       - Pop from stack and compute days difference
    3. Why monotonically decreasing? We want to find "next greater"
       - Stack contains indices waiting for a warmer day
       - Since we process left to right, stack naturally decreases

    COMPLEXITY:
    ──────────
    Time: O(n) — Each index pushed and popped at most once
    Space: O(n) — Stack can hold up to n indices
    """
    n = len(temperatures)
    result = [0] * n
    stack = []  # indices with decreasing temperatures

    for i in range(n):
        # While current temp > temp at top of stack
        while stack and temperatures[i] > temperatures[stack[-1]]:
            idx = stack.pop()
            result[idx] = i - idx
        stack.append(i)

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Largest Rectangle in Histogram
# ════════════════════════════════════════════════════════════════════════

def largest_rectangle_area(heights: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given an array of bar heights in a histogram, find the largest
    rectangle that can be formed.

    Example:
        Input: [2, 1, 5, 6, 2, 3]
        Output: 10  (5 x 2 rectangle at indices 2-3)

    THOUGHT PROCESS:
    ────────────────
    1. Brute Force: For each bar, expand left and right — O(n²)
    2. Monotonic Increasing Stack:
       - Process bars left to right, maintaining increasing heights in stack
       - When we see a shorter bar, we know the right boundary for the
         popped bar (current index). Left boundary is the new stack top
       - Area = height * (right_boundary - left_boundary - 1)
    3. Why increasing stack: When heights increase, rectangles can extend
       to the right. When a shorter bar appears, we "finalize" rectangles
       that can't extend further.
    4. Append 0 to handle remaining bars in stack at the end

    COMPLEXITY:
    ──────────
    Time: O(n) — Each bar pushed and popped at most once
    Space: O(n) — Stack stores indices
    """
    stack = []  # indices with increasing heights
    max_area = 0
    heights = heights + [0]  # Sentinel to force processing remaining bars

    for i, h in enumerate(heights):
        # Pop while current height < height at stack top
        while stack and h < heights[stack[-1]]:
            height = heights[stack.pop()]
            # Left boundary is the new stack top (or -1 if empty)
            left = stack[-1] if stack else -1
            width = i - left - 1
            max_area = max(max_area, height * width)
        stack.append(i)

    return max_area


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Evaluate Reverse Polish Notation
# ════════════════════════════════════════════════════════════════════════

def eval_rpn(tokens: List[str]) -> int:
    """
    QUESTION:
    ─────────
    Evaluate the value of an arithmetic expression in Reverse Polish
    Notation. Valid operators: +, -, *, /. Division truncates toward zero.

    Example:
        Input: ["2", "1", "+", "3", "*"]
        Output: 9  ((2 + 1) * 3)

    THOUGHT PROCESS:
    ────────────────
    1. Stack-based evaluation:
       - Push numbers onto stack
       - When encountering operator, pop two operands, compute, push result
    2. Order matters: For subtraction and division, second pop is left operand
       e.g., "5 3 -" → pop 3, then pop 5 → 5 - 3 = 2
    3. Integer division: Use int(a / b) for truncation toward zero
       (Python's // floors toward negative infinity, not truncates)

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass through tokens
    Space: O(n) — Stack can hold up to n/2 elements
    """
    stack = []

    for token in tokens:
        if token in ('+', '-', '*', '/'):
            b = stack.pop()
            a = stack.pop()

            if token == '+':
                stack.append(a + b)
            elif token == '-':
                stack.append(a - b)
            elif token == '*':
                stack.append(a * b)
            else:  # division: truncate toward zero
                stack.append(int(a / b))
        else:
            stack.append(int(token))

    return stack[0]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Next Greater Element (Circular)
# ════════════════════════════════════════════════════════════════════════

def next_greater_elements(nums: List[int]) -> List[int]:
    """
    QUESTION:
    ─────────
    Given a circular array, find the Next Greater Element for every element.
    The next greater element is the first greater number in a traversal
    order (including wrapping around).

    Example:
        Input: [1, 2, 1]
        Output: [2, -1, 2]

    THOUGHT PROCESS:
    ────────────────
    1. Circular array trick: Process the array twice (simulate by
       iterating 2*n with modulo index)
    2. Use monotonic decreasing stack (like daily temperatures)
    3. Only push results for first n elements (not duplicates)
    4. Stack stores indices of elements waiting for next greater

    COMPLEXITY:
    ──────────
    Time: O(n) — Each element processed twice, stack operations O(1)
    Space: O(n) — Result array + stack
    """
    n = len(nums)
    result = [-1] * n
    stack = []  # indices waiting for next greater element

    # Iterate twice to handle circularity
    for i in range(2 * n):
        idx = i % n
        while stack and nums[idx] > nums[stack[-1]]:
            popped = stack.pop()
            if result[popped] == -1:  # Only set once
                result[popped] = nums[idx]
        # Only push indices from first pass
        if i < n:
            stack.append(idx)

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Validate Stack Sequences
# ════════════════════════════════════════════════════════════════════════

def validate_stack_sequences(pushed: List[int], popped: List[int]) -> bool:
    """
    QUESTION:
    ─────────
    Given two sequences pushed and popped, return true if this could
    be the result of stack push/pop operations.

    Example:
        Input: pushed = [1,2,3,4,5], popped = [4,5,3,2,1]
        Output: true
        Input: pushed = [1,2,3,4,5], popped = [4,3,5,1,2]
        Output: false

    THOUGHT PROCESS:
    ────────────────
    1. Simulate the process: push elements until top matches next pop
    2. Greedy: Always pop when the top of stack matches the next element
       in popped sequence
    3. If all elements are pushed and stack is empty → valid sequence
    4. This works because at any point, if we can pop, we should
       (delaying pop can never help create a valid sequence)

    COMPLEXITY:
    ──────────
    Time: O(n) — Each element pushed and popped at most once
    Space: O(n) — Stack storage
    """
    stack = []
    pop_idx = 0

    for num in pushed:
        stack.append(num)

        # Greedily pop while top matches next popped element
        while stack and stack[-1] == popped[pop_idx]:
            stack.pop()
            pop_idx += 1

    return len(stack) == 0


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Decode String
# ════════════════════════════════════════════════════════════════════════

def decode_string(s: str) -> str:
    """
    QUESTION:
    ─────────
    Given an encoded string, return its decoded string.
    Encoding: k[encoded_string] means the encoded_string is repeated k times.

    Example:
        Input: "3[a]2[bc]"
        Output: "aaabcbc"
        Input: "3[a2[c]]"
        Output: "accaccacc"

    THOUGHT PROCESS:
    ────────────────
    1. Use stack to handle nested encodings
    2. Two stacks: one for counts, one for partial strings
    3. When we see '[', push current count and current string to stacks
    4. When we see ']', pop and build → repeat current string and append
       to previous string
    5. This naturally handles nesting because inner brackets are processed
       first (LIFO property of stack)

    COMPLEXITY:
    ──────────
    Time: O(n) — Each character processed once
    Space: O(n) — Stack stores intermediate strings
    """
    count_stack = []
    string_stack = []
    current_string = ""
    current_count = 0

    for char in s:
        if char.isdigit():
            current_count = current_count * 10 + int(char)
        elif char == '[':
            count_stack.append(current_count)
            string_stack.append(current_string)
            current_string = ""
            current_count = 0
        elif char == ']':
            count = count_stack.pop()
            prev_string = string_stack.pop()
            current_string = prev_string + current_string * count
        else:
            current_string += char

    return current_string


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("STACKS — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Valid Parentheses")
    print("-" * 40)
    tests = ["()[]{}", "([)]", "({[]})"]
    for t in tests:
        print(f"   \"{t}\": {is_valid_parentheses(t)}")

    # Q2
    print("\n2️⃣  Min Stack")
    print("-" * 40)
    ms = MinStack()
    ms.push(-2)
    ms.push(0)
    ms.push(-3)
    print(f"   After pushes [-2, 0, -3]:")
    print(f"   getMin(): {ms.get_min()}")
    ms.pop()
    print(f"   After pop:")
    print(f"   top(): {ms.top()}")
    print(f"   getMin(): {ms.get_min()}")

    # Q3
    print("\n3️⃣  Daily Temperatures")
    print("-" * 40)
    temps = [73, 74, 75, 71, 69, 72, 76, 73]
    print(f"   Input: {temps}")
    print(f"   Output: {daily_temperatures(temps)}")

    # Q4
    print("\n4️⃣  Largest Rectangle in Histogram")
    print("-" * 40)
    heights = [2, 1, 5, 6, 2, 3]
    print(f"   Input: {heights}")
    print(f"   Largest Area: {largest_rectangle_area(heights)}")

    # Q5
    print("\n5️⃣  Evaluate Reverse Polish Notation")
    print("-" * 40)
    tokens = ["2", "1", "+", "3", "*"]
    print(f"   Input: {tokens}")
    print(f"   Result: {eval_rpn(tokens)}")

    # Q6
    print("\n6️⃣  Next Greater Element (Circular)")
    print("-" * 40)
    nums = [1, 2, 1]
    print(f"   Input: {nums}")
    print(f"   Output: {next_greater_elements(nums)}")

    # Q7
    print("\n7️⃣  Validate Stack Sequences")
    print("-" * 40)
    pushed = [1, 2, 3, 4, 5]
    popped1 = [4, 5, 3, 2, 1]
    popped2 = [4, 3, 5, 1, 2]
    print(f"   pushed={pushed}")
    print(f"   popped={popped1}: {validate_stack_sequences(pushed, popped1)}")
    print(f"   popped={popped2}: {validate_stack_sequences(pushed, popped2)}")

    # Q8
    print("\n8️⃣  Decode String")
    print("-" * 40)
    tests = ["3[a]2[bc]", "3[a2[c]]"]
    for t in tests:
        print(f"   \"{t}\" → \"{decode_string(t)}\"")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
