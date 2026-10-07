"""
DYNAMIC PROGRAMMING — Core Concepts & Interview Questions
==========================================================

Core Concepts:
──────────────
• DP is optimization over recursion — solves overlapping subproblems
• Two key properties:
  1. Optimal Substructure: Optimal solution uses optimal sub-solutions
  2. Overlapping Subproblems: Same subproblems solved repeatedly
• Two approaches:
  - Top-down (Memoization): Recursive + caching, more intuitive
  - Bottom-up (Tabulation): Iterative, no recursion-depth limit, and
    often allows rolling-array space savings (keep only the rows needed)
• Interview flow that works: brute-force recursion → add memo (top-down)
  → convert to a table (bottom-up) → shrink the table

Thinking Framework:
───────────────────
1. Define state: What does dp[i] or dp[i][j] represent?
2. Find recurrence: How does dp[i] relate to previous states?
3. Identify base cases: Smallest subproblems
4. Determine iteration order: Loop direction matters

Common Patterns:
────────────────
• 1D DP: Fibonacci, climb stairs, house robber
• 2D DP: Grid paths, LCS, edit distance
• Knapsack variants: 0/1, unbounded, subset sum
• Interval DP: Matrix chain multiplication, palindrome partitioning
• DP on trees: Diameter, max path sum
• State machine: Buy/sell stock with cooldown
"""

from typing import List, Optional, Tuple


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Fibonacci Number (Memoization vs Tabulation)
# ════════════════════════════════════════════════════════════════════════

def fibonacci(n: int) -> int:
    """
    QUESTION:
    ─────────
    Calculate the nth Fibonacci number.

    THOUGHT PROCESS:
    ────────────────
    1. Recursive: fib(n) = fib(n-1) + fib(n-2) — exponential, O(φⁿ)
       ≈ O(1.618ⁿ) calls (often quoted loosely as O(2ⁿ))
    2. Memoization: Cache results — O(n) time, O(n) space
       (in Python: @functools.cache; still recursion-depth limited)
    3. Tabulation: Build from bottom — O(n) time, O(1) space
    4. Key insight: We only need last two values, not entire array
    5. Faster: matrix exponentiation / fast doubling — O(log n)
       arithmetic operations. In Java/Go, fib(93) already overflows a
       signed 64-bit integer; LeetCode-style problems ask for it mod 1e9+7.

    COMPLEXITY:
    ──────────
    Time: O(n) — Linear iterations
    Space: O(1) — Only two variables
    """
    if n <= 1:
        return n

    prev2, prev1 = 0, 1

    for _ in range(2, n + 1):
        current = prev1 + prev2
        prev2 = prev1
        prev1 = current

    return prev1


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Climbing Stairs
# ════════════════════════════════════════════════════════════════════════

def climb_stairs(n: int) -> int:
    """
    QUESTION:
    ─────────
    You are climbing a staircase with n steps. Each time you can climb
    1 or 2 steps. How many distinct ways to reach the top?

    Example:
        Input: n = 3
        Output: 3  (1+1+1, 1+2, 2+1)

    THOUGHT PROCESS:
    ────────────────
    1. State: dp[i] = ways to reach step i
    2. Recurrence: dp[i] = dp[i-1] + dp[i-2]
       (reach step i from i-1 with 1 step, or from i-2 with 2 steps)
    3. Base: dp[0] = 1, dp[1] = 1
    4. This is essentially Fibonacci with different base

    COMPLEXITY:
    ──────────
    Time: O(n) — Linear
    Space: O(1) — Space optimized
    """
    if n <= 1:
        return 1

    prev2, prev1 = 1, 1

    for _ in range(2, n + 1):
        current = prev1 + prev2
        prev2 = prev1
        prev1 = current

    return prev1


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Coin Change (Fewest coins to make amount)
# ════════════════════════════════════════════════════════════════════════

def coin_change(coins: List[int], amount: int) -> int:
    """
    QUESTION:
    ─────────
    Given an array of coin denominations and a total amount, find the
    fewest number of coins needed to make that amount. If impossible, -1.

    Example:
        Input: coins = [1, 2, 5], amount = 11
        Output: 3  (5 + 5 + 1)

    THOUGHT PROCESS:
    ────────────────
    1. State: dp[i] = fewest coins to make amount i
    2. Recurrence: dp[i] = min(dp[i], 1 + dp[i - coin]) for each coin
    3. Base: dp[0] = 0 (0 coins to make amount 0)
    4. Initialize dp with amount+1 (sentinel for "impossible")
    5. For each amount, try every coin — this is a classic unbounded knapsack
    6. Why not greedy (largest coin first)? It fails for non-canonical
       coin systems: coins [1, 3, 4], amount 6 → greedy 4+1+1 = 3 coins,
       optimal 3+3 = 2 coins.
    7. Variant "number of ways" (Coin Change II): loop coins OUTER and
       amounts inner, so each combination is counted once, not once per
       ordering.

    COMPLEXITY:
    ──────────
    Time: O(amount × coins) — Nested loops
    Space: O(amount) — DP array
    """
    # Initialize with amount+1 (greater than any possible answer)
    dp = [amount + 1] * (amount + 1)
    dp[0] = 0

    for i in range(1, amount + 1):
        for coin in coins:
            if coin <= i:
                dp[i] = min(dp[i], 1 + dp[i - coin])

    return dp[amount] if dp[amount] != amount + 1 else -1


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Longest Increasing Subsequence (LIS)
# ════════════════════════════════════════════════════════════════════════

def length_of_lis(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given an integer array, find the length of the longest strictly
    increasing subsequence.

    Example:
        Input: [10, 9, 2, 5, 3, 7, 101, 18]
        Output: 4  ([2, 3, 7, 101])

    THOUGHT PROCESS:
    ────────────────
    1. DP approach (O(n²)):
       - State: dp[i] = LIS ending at index i
       - Recurrence: dp[i] = max(dp[i], 1 + dp[j]) for j < i and nums[j] < nums[i]
       - Result: max(dp)
    2. Patience Sorting approach (O(n log n)):
       - Maintain array tail[i] = smallest tail of increasing subsequence of length i+1
       - For each num, use binary search to find where it fits
       - If num > all tails, append; else, replace the smallest tail ≥ num
    3. Key insight: We only care about the smallest possible tail value
       for each subsequence length (greedy). `tails` stays sorted, which
       is what makes the binary search valid.
    4. Caveat: `tails` is NOT itself an LIS; to reconstruct one, store a
       predecessor index for each element.
    5. bisect_left gives STRICTLY increasing; use bisect_right for
       non-decreasing subsequences.

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Binary search for each element
    Space: O(n) — Tails array
    """
    import bisect

    tails = []

    for num in nums:
        # Find position where num would be inserted
        idx = bisect.bisect_left(tails, num)
        if idx == len(tails):
            tails.append(num)
        else:
            tails[idx] = num  # Replace with smaller value

    return len(tails)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Longest Common Subsequence (LCS)
# ════════════════════════════════════════════════════════════════════════

def longest_common_subsequence(text1: str, text2: str) -> int:
    """
    QUESTION:
    ─────────
    Given two strings, find the length of their longest common subsequence.
    A subsequence is a sequence derived by deleting some characters.

    Example:
        Input: text1 = "abcde", text2 = "ace"
        Output: 3  ("ace")

    THOUGHT PROCESS:
    ────────────────
    1. State: dp[i][j] = LCS of text1[0:i] and text2[0:j]
    2. Recurrence:
       - If text1[i-1] == text2[j-1]: dp[i][j] = 1 + dp[i-1][j-1]
       - Else: dp[i][j] = max(dp[i-1][j], dp[i][j-1])
    3. This is a classic 2D DP — visualization as grid traversal
    4. Space optimization: Only need previous row (2 rows suffice)

    COMPLEXITY:
    ──────────
    Time: O(m × n) — Fill entire DP table
    Space: O(min(m, n)) — Optimized to single row
    """
    m, n = len(text1), len(text2)

    # Use smaller dimension for space optimization
    if m < n:
        text1, text2 = text2, text1
        m, n = n, m

    prev = [0] * (n + 1)

    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if text1[i - 1] == text2[j - 1]:
                curr[j] = 1 + prev[j - 1]
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev = curr

    return prev[n]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: 0/1 Knapsack
# ════════════════════════════════════════════════════════════════════════

def knapsack(weights: List[int], values: List[int], capacity: int) -> int:
    """
    QUESTION:
    ─────────
    Given items with weights and values, and a knapsack capacity,
    find the maximum value you can carry. Each item can be taken at most once.

    Example:
        Input: weights=[1,3,4,5], values=[1,4,5,7], capacity=7
        Output: 9  (items with weight 3+4 = value 4+5 = 9, or 5+1 = 1+7=8)

    THOUGHT PROCESS:
    ────────────────
    1. State: dp[i][w] = max value with first i items and capacity w
    2. At each item, we have two choices:
       - Skip item i: dp[i-1][w]
       - Take item i (if weight[i] ≤ w): value[i] + dp[i-1][w - weight[i]]
    3. dp[i][w] = max(skip, take)
    4. Space optimization: 1D array, iterate capacity BACKWARDS so that
       dp[w - weight] still holds the previous item's row. Iterating
       forwards would let the same item be taken again — which is
       exactly the unbounded knapsack.
    5. O(n × capacity) is pseudo-polynomial: polynomial in the VALUE of
       capacity, exponential in its bit length. 0/1 knapsack is NP-hard.

    COMPLEXITY:
    ──────────
    Time: O(n × capacity) — n items × capacity
    Space: O(capacity) — With 1D optimization
    """
    n = len(weights)
    dp = [0] * (capacity + 1)

    for i in range(n):
        # Iterate backwards to avoid reusing item multiple times
        for w in range(capacity, weights[i] - 1, -1):
            dp[w] = max(dp[w], values[i] + dp[w - weights[i]])

    return dp[capacity]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Edit Distance (Levenshtein Distance)
# ════════════════════════════════════════════════════════════════════════

def min_distance(word1: str, word2: str) -> int:
    """
    QUESTION:
    ─────────
    Given two strings, find the minimum number of operations (insert,
    delete, replace) to convert word1 into word2.

    Example:
        Input: word1 = "horse", word2 = "ros"
        Output: 3  (horse → rorse → rose → ros)

    THOUGHT PROCESS:
    ────────────────
    1. State: dp[i][j] = edit distance between word1[0:i] and word2[0:j]
    2. Recurrence:
       - If word1[i-1] == word2[j-1]: dp[i][j] = dp[i-1][j-1]
       - Else: dp[i][j] = 1 + min(
           dp[i-1][j],    # Delete from word1
           dp[i][j-1],    # Insert into word1
           dp[i-1][j-1]   # Replace
         )
    3. Base: dp[i][0] = i (delete all), dp[0][j] = j (insert all)
    4. The code swaps the strings so the row is the shorter one. That is
       safe because edit distance is symmetric (an insert one way is a
       delete the other way).

    COMPLEXITY:
    ──────────
    Time: O(m × n) — Full DP table
    Space: O(min(m, n)) — Optimized (needs the full table if you must
           reconstruct the actual edit script)
    """
    m, n = len(word1), len(word2)

    # Use smaller dimension for space
    if m < n:
        word1, word2 = word2, word1
        m, n = n, m

    prev = list(range(n + 1))

    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        curr[0] = i  # Delete all characters
        for j in range(1, n + 1):
            if word1[i - 1] == word2[j - 1]:
                curr[j] = prev[j - 1]
            else:
                curr[j] = 1 + min(
                    prev[j],     # Delete
                    curr[j - 1], # Insert
                    prev[j - 1]  # Replace
                )
        prev = curr

    return prev[n]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Maximum Product Subarray
# ════════════════════════════════════════════════════════════════════════

def max_product_subarray(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Find the contiguous subarray with the largest product.

    Example:
        Input: [2, 3, -2, 4]
        Output: 6  (subarray [2, 3] = 6)

    THOUGHT PROCESS:
    ────────────────
    1. Unlike max sum, product has a twist: negative * negative = positive
    2. We need to track both max and min at each position
       - max_ending = max(nums[i], max_ending * nums[i], min_ending * nums[i])
       - min_ending = min(nums[i], max_ending * nums[i], min_ending * nums[i])
    3. A negative number can turn min into max (and vice versa)
    4. Key insight: Need to track both extremes, not just max
    5. Zeros reset both extremes (the `num` candidate restarts the run)
    6. Java/Go: products overflow quickly; LeetCode guarantees the answer
       fits in 32 bits, but intermediate min/max may not — use long

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass
    Space: O(1) — Only variables
    """
    if not nums:
        return 0

    max_ending = min_ending = nums[0]
    global_max = nums[0]

    for i in range(1, len(nums)):
        num = nums[i]

        # Compute new max/min using previous extremes
        candidates = (num, max_ending * num, min_ending * num)
        max_ending = max(candidates)
        min_ending = min(candidates)

        global_max = max(global_max, max_ending)

    return global_max


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: House Robber
# ════════════════════════════════════════════════════════════════════════

def rob(nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    You are a robber planning to rob houses along a street. Adjacent
    houses have security systems that will alert police if two adjacent
    houses are robbed. Find the maximum amount you can rob.

    Example:
        Input: [1, 2, 3, 1]
        Output: 4  (rob house 1=1 + house 3=3 = 4)

    THOUGHT PROCESS:
    ────────────────
    1. State: dp[i] = max money up to house i
    2. At each house, two choices:
       - Rob it: nums[i] + dp[i-2] (skip previous)
       - Skip it: dp[i-1]
    3. dp[i] = max(nums[i] + dp[i-2], dp[i-1])
    4. Space optimize: only need prev and prev2
    5. Variants: houses in a circle (run twice: without the first house,
       without the last); houses in a tree (return (rob, skip) per node)

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass
    Space: O(1) — Two variables
    """
    if not nums:
        return 0
    if len(nums) == 1:
        return nums[0]

    prev2, prev1 = nums[0], max(nums[0], nums[1])

    for i in range(2, len(nums)):
        current = max(nums[i] + prev2, prev1)
        prev2, prev1 = prev1, current

    return prev1


# ════════════════════════════════════════════════════════════════════════
# QUESTION 10: Unique Paths (Grid DP)
# ════════════════════════════════════════════════════════════════════════

def unique_paths(m: int, n: int) -> int:
    """
    QUESTION:
    ─────────
    A robot is at top-left of an m×n grid. It can only move down or right.
    How many unique paths to the bottom-right corner?

    Example:
        Input: m = 3, n = 7
        Output: 28

    THOUGHT PROCESS:
    ────────────────
    1. State: dp[i][j] = unique paths to cell (i, j)
    2. Recurrence: dp[i][j] = dp[i-1][j] + dp[i][j-1]
       (paths from top + paths from left)
    3. Base: dp[0][j] = 1 (only one way along top row)
       dp[i][0] = 1 (only one way along left column)
    4. Space optimize: only need current and previous row
    5. Closed form: choose which (m-1) of the (m+n-2) moves go down:
       C(m+n-2, m-1) — math.comb in Python. The DP still matters because
       it extends to obstacles and weighted grids.

    COMPLEXITY:
    ──────────
    Time: O(m × n) — Fill grid
    Space: O(n) — Single row
    """
    # Initialize first row: dp[j] = 1 for all j
    dp = [1] * n

    for i in range(1, m):
        for j in range(1, n):
            dp[j] += dp[j - 1]  # dp[j] = previous row's dp[j] + current row's dp[j-1]

    return dp[-1]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 11: Palindrome Partitioning (Min Cuts)
# ════════════════════════════════════════════════════════════════════════

def min_cut(s: str) -> int:
    """
    QUESTION:
    ─────────
    Given a string s, partition it such that every substring is a
    palindrome. Return the minimum cuts needed.

    Example:
        Input: "aab"
        Output: 1  ("aa" | "b")

    THOUGHT PROCESS:
    ────────────────
    1. State: dp[i] = min cuts for s[0:i+1]
    2. For each position, check all palindromes ending at that position
    3. If s[j:i] is palindrome: dp[i] = min(dp[i], 1 + dp[j-1])
    4. Precompute palindrome table: is_pal[i][j] = palindrome?

    COMPLEXITY:
    ──────────
    Time: O(n²) — O(n²) to build the palindrome table, O(n²) for the cuts
    Space: O(n²) — Palindrome table (O(n) with center expansion that
           updates dp directly)
    """
    n = len(s)
    if n <= 1:
        return 0

    # Precompute palindrome table
    is_pal = [[False] * n for _ in range(n)]
    for i in range(n):
        is_pal[i][i] = True
    for length in range(2, n + 1):
        for i in range(n - length + 1):
            j = i + length - 1
            if s[i] == s[j] and (length <= 2 or is_pal[i + 1][j - 1]):
                is_pal[i][j] = True

    # DP for min cuts
    dp = [float('inf')] * n
    for i in range(n):
        if is_pal[0][i]:
            dp[i] = 0
        else:
            for j in range(i):
                if is_pal[j + 1][i]:
                    dp[i] = min(dp[i], 1 + dp[j])

    return dp[-1]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 12: Word Break
# ════════════════════════════════════════════════════════════════════════

def word_break(s: str, word_dict: List[str]) -> bool:
    """
    QUESTION:
    ─────────
    Return True if s can be split into a sequence of one or more
    dictionary words (words may be reused).

    Example:
        Input: s = "applepenapple", wordDict = ["apple", "pen"]
        Output: True
        Input: s = "catsandog", wordDict = ["cats","dog","sand","and","cat"]
        Output: False

    THOUGHT PROCESS:
    ────────────────
    1. Brute force recursion tries every prefix: exponential on inputs
       like "aaaa...ab" with dict ["a", "aa", "aaa"].
    2. The subproblem "can s[i:] be segmented?" repeats → DP.
    3. State: dp[i] = True if s[:i] can be segmented. dp[0] = True.
       dp[i] = any(dp[j] and s[j:i] in words) over j < i.
    4. Only try j within the longest word's length of i: that bounds the
       inner loop by L instead of n.
    5. Word Break II (return all sentences) can produce exponentially many
       answers; memoize suffix → list of sentences, and check the boolean
       version first.

    COMPLEXITY:
    ──────────
    Time: O(n · L · L) — n end positions, L start positions each, and
          O(L) to slice and hash each candidate (L = longest word)
    Space: O(n + total dictionary size)

    EDGE CASES:
    ──────────
    • Empty dictionary → False for any non-empty s
    • A trie over the dictionary lets one walk from j find all words
      starting at j without slicing (helps with huge dictionaries)
    """
    words = set(word_dict)
    max_len = max(map(len, words), default=0)
    n = len(s)
    dp = [False] * (n + 1)
    dp[0] = True

    for i in range(1, n + 1):
        for j in range(max(0, i - max_len), i):
            if dp[j] and s[j:i] in words:
                dp[i] = True
                break

    return dp[n]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 13: Decode Ways
# ════════════════════════════════════════════════════════════════════════

def num_decodings(s: str) -> int:
    """
    QUESTION:
    ─────────
    Letters are encoded 'A' → "1" ... 'Z' → "26". Given a digit string,
    count the ways to decode it.

    Example:
        Input: "226"
        Output: 3  ("BZ" = 2|26, "VF" = 22|6, "BBF" = 2|2|6)

    THOUGHT PROCESS:
    ────────────────
    1. Climbing-stairs shape (Q2): the last step consumes one digit or
       two, so dp[i] = (ways using one digit) + (ways using two).
    2. Conditions are the whole problem:
       - One digit s[i-1] is valid iff it is not '0'
       - Two digits s[i-2:i] are valid iff 10 ≤ value ≤ 26
         ("06" is NOT a valid two-digit code)
    3. dp[0] = 1 (empty prefix). Only the last two values are needed.

    COMPLEXITY:
    ──────────
    Time: O(n) — One pass
    Space: O(1) — Two rolling variables

    EDGE CASES:
    ──────────
    • Leading '0' or "00" anywhere → 0
    • "10", "20" → 1 (the zero must pair with the digit before it)
    • "27" → 1 (27 is not a letter)
    """
    if not s:
        return 0

    prev2, prev1 = 1, 1 if s[0] != '0' else 0   # dp[i-2], dp[i-1]

    for i in range(2, len(s) + 1):
        current = 0
        if s[i - 1] != '0':
            current += prev1                     # Single digit
        if 10 <= int(s[i - 2:i]) <= 26:
            current += prev2                     # Two digits
        prev2, prev1 = prev1, current

    return prev1


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("DYNAMIC PROGRAMMING — Interview Questions Demo")
    print("=" * 70)

    print("\n1️⃣  Fibonacci")
    print("-" * 40)
    print(f"   fib(10): {fibonacci(10)}")

    print("\n2️⃣  Climbing Stairs")
    print("-" * 40)
    print(f"   climbStairs(5): {climb_stairs(5)}")

    print("\n3️⃣  Coin Change")
    print("-" * 40)
    print(f"   coins=[1,2,5], amount=11: {coin_change([1, 2, 5], 11)}")
    print(f"   coins=[2], amount=3: {coin_change([2], 3)}")

    print("\n4️⃣  Longest Increasing Subsequence")
    print("-" * 40)
    nums = [10, 9, 2, 5, 3, 7, 101, 18]
    print(f"   Input: {nums}")
    print(f"   LIS length: {length_of_lis(nums)}")

    print("\n5️⃣  Longest Common Subsequence")
    print("-" * 40)
    print(f"   \"abcde\" vs \"ace\": {longest_common_subsequence('abcde', 'ace')}")

    print("\n6️⃣  0/1 Knapsack")
    print("-" * 40)
    weights, values, capacity = [1, 3, 4, 5], [1, 4, 5, 7], 7
    print(f"   weights={weights}, values={values}, capacity={capacity}")
    print(f"   Max value: {knapsack(weights, values, capacity)}")

    print("\n7️⃣  Edit Distance")
    print("-" * 40)
    print(f"   \"horse\" → \"ros\": {min_distance('horse', 'ros')}")

    print("\n8️⃣  Maximum Product Subarray")
    print("-" * 40)
    nums = [2, 3, -2, 4]
    print(f"   Input: {nums}")
    print(f"   Max product: {max_product_subarray(nums)}")

    print("\n9️⃣  House Robber")
    print("-" * 40)
    print(f"   [1,2,3,1]: {rob([1, 2, 3, 1])}")
    print(f"   [2,7,9,3,1]: {rob([2, 7, 9, 3, 1])}")

    print("\n🔟  Unique Paths")
    print("-" * 40)
    print(f"   3×7 grid: {unique_paths(3, 7)}")

    print("\n1️⃣1️⃣  Palindrome Partitioning")
    print("-" * 40)
    print(f"   \"aab\": {min_cut('aab')}")
    print(f"   \"ab\": {min_cut('ab')}")

    print("\n1️⃣2️⃣  Word Break")
    print("-" * 40)
    print(f"   \"applepenapple\", [apple, pen]: {word_break('applepenapple', ['apple', 'pen'])}")
    print(f"   \"catsandog\", [cats, dog, sand, and, cat]: "
          f"{word_break('catsandog', ['cats', 'dog', 'sand', 'and', 'cat'])}")

    print("\n1️⃣3️⃣  Decode Ways")
    print("-" * 40)
    for code in ("12", "226", "06", "10"):
        print(f"   \"{code}\": {num_decodings(code)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
