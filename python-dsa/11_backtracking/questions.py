"""
BACKTRACKING — Core Concepts & Interview Questions
===================================================

Core Concepts:
──────────────
• Systematically searches for all solutions by building candidates
  incrementally and abandoning (backtracking) when a candidate cannot
  lead to a valid solution
• Key difference from brute force: prunes search space by detecting
  dead ends early
• Typically implemented with recursion — each recursive call represents
  a "decision" (include/exclude, choose next element)
• Pruning strategies: constraint checking, bounding functions,
  ordering heuristics (choose most constrained first)

Backtracking Template:
──────────────────────
def backtrack(candidate, state):
    if is_valid_solution(candidate):
        result.append(candidate.copy())
        return     # or continue searching for all solutions

    for next_choice in choices:
        if is_valid_choice(next_choice, state):
            make_choice(next_choice, state)
            backtrack(candidate, state)
            undo_choice(next_choice, state)  # backtrack!

Common Patterns:
────────────────
• Subsets / Combinations — include/exclude each element
• Permutations — reorder elements, track used
• N-Queens — place queens row by row, check column/diagonal conflicts
• Sudoku — fill empty cells, check row/col/box constraints
• Word Search — DFS from each cell, mark visited
• Generate Parentheses — track open/close counts
• Graph coloring — assign colors, check adjacent constraints
"""

from typing import List, Optional, Tuple
from collections import Counter
import copy


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Subsets (Power Set)
# ════════════════════════════════════════════════════════════════════════

def subsets(nums: List[int]) -> List[List[int]]:
    """
    QUESTION:
    ─────────
    Given an array of distinct integers, return all possible subsets
    (the power set).

    Example:
        Input: nums = [1, 2, 3]
        Output: [[], [1], [2], [1,2], [3], [1,3], [2,3], [1,2,3]]

    THOUGHT PROCESS:
    ────────────────
    1. At each element, we have two choices: include or exclude
    2. Two equivalent recursion shapes:
       a) Binary include/exclude tree: record the subset only at the
          leaves (after deciding all n elements)
       b) "Pick the next element" loop (used below): every node of the
          tree is a valid subset, so record it on entry; the loop from
          `start` guarantees each subset is built in increasing index
          order exactly once
    3. The "choose → recurse → un-choose" pattern is the foundation of
       backtracking
    4. Alternatives: iterative (start with [[]], for each num, add num
       to each existing subset), or bitmasks 0..2ⁿ-1

    COMPLEXITY:
    ──────────
    Time: O(n × 2ⁿ) — 2ⁿ subsets, each copied to result
    Space: O(n) — Recursion depth (not counting output)
    """
    result = []

    def backtrack(start: int, current: List[int]) -> None:
        result.append(current[:])  # Add current subset

        for i in range(start, len(nums)):
            # Include nums[i]
            current.append(nums[i])
            backtrack(i + 1, current)
            current.pop()  # Exclude (backtrack)

    backtrack(0, [])
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Subsets II (with Duplicates)
# ════════════════════════════════════════════════════════════════════════

def subsets_with_duplicates(nums: List[int]) -> List[List[int]]:
    """
    QUESTION:
    ─────────
    Given an array with possible duplicates, return all possible subsets.
    The solution set must not contain duplicate subsets.

    Example:
        Input: nums = [1, 2, 2]
        Output: [[], [1], [2], [1,2], [2,2], [1,2,2]]

    THOUGHT PROCESS:
    ────────────────
    1. Sort first so duplicates are adjacent
    2. When we encounter duplicates, only include the first one at
       each decision level — this avoids generating the same subset
       multiple ways
    3. Key pruning rule: skip nums[i] if nums[i] == nums[i-1] AND
       i > start (not i > 0)

    COMPLEXITY:
    ──────────
    Time: O(n × 2ⁿ) — Still bounded by subset count
    Space: O(n) — Recursion depth
    """
    nums.sort()
    result = []

    def backtrack(start: int, current: List[int]) -> None:
        result.append(current[:])

        for i in range(start, len(nums)):
            # Skip duplicates at the same recursion level
            if i > start and nums[i] == nums[i - 1]:
                continue
            current.append(nums[i])
            backtrack(i + 1, current)
            current.pop()

    backtrack(0, [])
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Permutations
# ════════════════════════════════════════════════════════════════════════

def permute(nums: List[int]) -> List[List[int]]:
    """
    QUESTION:
    ─────────
    Given an array of distinct integers, return all possible permutations.

    Example:
        Input: nums = [1, 2, 3]
        Output: [[1,2,3],[1,3,2],[2,1,3],[2,3,1],[3,1,2],[3,2,1]]

    THOUGHT PROCESS:
    ────────────────
    1. Unlike subsets, order matters for permutations
    2. At each position, we can place any remaining element
    3. Track which elements have been used (boolean array or used set)
    4. Or swap-based: swap each element into current position, recurse,
       then swap back
    5. The swap approach is more space-efficient (no extra used array)

    COMPLEXITY:
    ──────────
    Time: O(n × n!) — n! permutations, each copied to result
    Space: O(n) — Recursion depth
    """

    def backtrack(current: List[int], used: List[bool]) -> None:
        if len(current) == len(nums):
            result.append(current[:])
            return

        for i in range(len(nums)):
            if used[i]:
                continue
            used[i] = True
            current.append(nums[i])
            backtrack(current, used)
            current.pop()
            used[i] = False

    result = []
    backtrack([], [False] * len(nums))
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Permutations II (with Duplicates)
# ════════════════════════════════════════════════════════════════════════

def permute_unique(nums: List[int]) -> List[List[int]]:
    """
    QUESTION:
    ─────────
    Given a collection with possible duplicates, return all unique
    permutations.

    Example:
        Input: nums = [1, 1, 2]
        Output: [[1,1,2],[1,2,1],[2,1,1]]

    THOUGHT PROCESS:
    ────────────────
    1. Sort the array so duplicates are adjacent
    2. Skip nums[i] if:
       a) It's already used, OR
       b) It's same as previous AND previous is NOT used (meaning
          we're starting a new branch at this level)
    3. The condition: used[i-1] is False means we've already processed
       this value at this recursion level
    4. Net effect: equal values are always used in their sorted order,
       so a duplicate is never placed into the same position twice
    5. Alternative: iterate over a Counter of remaining values instead of
       indices — no sorting and no skip rule needed

    COMPLEXITY:
    ──────────
    Time: O(n × n!) — Bounded by unique permutations
    Space: O(n) — Recursion depth
    """
    nums.sort()
    result = []

    def backtrack(current: List[int], used: List[bool]) -> None:
        if len(current) == len(nums):
            result.append(current[:])
            return

        for i in range(len(nums)):
            if used[i]:
                continue
            # Skip duplicates: if same as previous and prev not used
            if i > 0 and nums[i] == nums[i - 1] and not used[i - 1]:
                continue

            used[i] = True
            current.append(nums[i])
            backtrack(current, used)
            current.pop()
            used[i] = False

    backtrack([], [False] * len(nums))
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Combination Sum (Unbounded)
# ════════════════════════════════════════════════════════════════════════

def combination_sum(candidates: List[int], target: int) -> List[List[int]]:
    """
    QUESTION:
    ─────────
    Given an array of distinct integers and a target, find all unique
    combinations where the numbers sum to target. The same number may
    be used unlimited times.

    Example:
        Input: candidates = [2, 3, 6, 7], target = 7
        Output: [[2, 2, 3], [7]]

    THOUGHT PROCESS:
    ────────────────
    1. Since we can reuse numbers, at each step we can either:
       - Take the current number again (not increment index)
       - Skip it and move to the next
    2. Pruning: If candidate > remaining target, skip
    3. Sort candidates for early termination
    4. This is a "unbounded knapsack" backtracking

    COMPLEXITY:
    ──────────
    Time: O(n^(target/min)) — Exponential, branching factor n
    Space: O(target/min) — Maximum depth of recursion
    """
    candidates.sort()
    result = []

    def backtrack(start: int, remaining: int, current: List[int]) -> None:
        if remaining == 0:
            result.append(current[:])
            return

        for i in range(start, len(candidates)):
            if candidates[i] > remaining:
                break  # Pruning: sorted array, rest are larger

            current.append(candidates[i])
            # i (not i+1) because we can reuse the same element
            backtrack(i, remaining - candidates[i], current)
            current.pop()

    backtrack(0, target, [])
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Combination Sum II (Limited Use)
# ════════════════════════════════════════════════════════════════════════

def combination_sum2(candidates: List[int], target: int) -> List[List[int]]:
    """
    QUESTION:
    ─────────
    Each number may be used only once. Find all unique combinations.

    Example:
        Input: candidates = [10, 1, 2, 7, 6, 1, 5], target = 8
        Output: [[1,1,6],[1,2,5],[1,7],[2,6]]

    THOUGHT PROCESS:
    ────────────────
    1. Each element can be used at most once → increment i by 1
    2. Since there are duplicates, skip same-valued elements
       at the same recursion depth (like subsets with duplicates)
    3. Prune when candidate > remaining

    COMPLEXITY:
    ──────────
    Time: O(2ⁿ) — Each element either taken or skipped
    Space: O(n) — Recursion depth
    """
    candidates.sort()
    result = []

    def backtrack(start: int, remaining: int, current: List[int]) -> None:
        if remaining == 0:
            result.append(current[:])
            return

        for i in range(start, len(candidates)):
            if candidates[i] > remaining:
                break
            # Skip duplicates
            if i > start and candidates[i] == candidates[i - 1]:
                continue

            current.append(candidates[i])
            backtrack(i + 1, remaining - candidates[i], current)
            current.pop()

    backtrack(0, target, [])
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: N-Queens
# ════════════════════════════════════════════════════════════════════════

def solve_n_queens(n: int) -> List[List[str]]:
    """
    QUESTION:
    ─────────
    Place N queens on an N×N chessboard such that no two queens attack
    each other (same row, column, or diagonal). Return all distinct
    solutions.

    Example:
        Input: n = 4
        Output: [[".Q..","...Q","Q...","..Q."], ["..Q.","Q...","...Q",".Q.."]]

    THOUGHT PROCESS:
    ────────────────
    1. Place queens row by row (one per row is guaranteed)
    2. For each row, try each column — check if position is safe
    3. Safety checks:
       - Column conflict: same column used
       - Diagonal conflict: |row - prev_row| == |col - prev_col|
    4. Use sets for O(1) conflict detection:
       - columns set
       - positive diagonal set (row + col is constant)
       - negative diagonal set (row - col is constant)
    5. Backtrack when no safe column in current row

    COMPLEXITY:
    ──────────
    Time: O(n!) — First row n choices, second n-1, etc. (an upper
          bound; diagonal pruning cuts far more in practice)
    Space: O(n²) — The board; the sets and recursion are O(n)
           (storing one column index per row instead of a board makes it
           O(n) overall)
    """
    cols = set()
    pos_diag = set()  # row + col
    neg_diag = set()  # row - col
    board = [['.'] * n for _ in range(n)]
    result = []

    def backtrack(row: int) -> None:
        if row == n:
            result.append([''.join(r) for r in board])
            return

        for col in range(n):
            if col in cols or (row + col) in pos_diag or (row - col) in neg_diag:
                continue

            # Place queen
            board[row][col] = 'Q'
            cols.add(col)
            pos_diag.add(row + col)
            neg_diag.add(row - col)

            backtrack(row + 1)

            # Remove queen (backtrack)
            board[row][col] = '.'
            cols.remove(col)
            pos_diag.remove(row + col)
            neg_diag.remove(row - col)

    backtrack(0)
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Generate Parentheses
# ════════════════════════════════════════════════════════════════════════

def generate_parentheses(n: int) -> List[str]:
    """
    QUESTION:
    ─────────
    Given n pairs of parentheses, generate all valid combinations.

    Example:
        Input: n = 3
        Output: ["((()))","(()())","(())()","()(())","()()()"]

    THOUGHT PROCESS:
    ────────────────
    1. At each position, we can place '(' if open < n
    2. Or we can place ')' if close < open
    3. The constraint "close < open" ensures validity
    4. Base case: when length = 2n, we have a valid combination
    5. This is a classic "Catalan number" problem

    COMPLEXITY:
    ──────────
    Time: O(4ⁿ/√n) — C_n = (2n)!/((n+1)!n!) ≈ 4ⁿ/(n^1.5·√π) results,
          each O(n) to build
    Space: O(n) — Recursion depth (2n), excluding output
    """
    result = []

    def backtrack(current: List[str], open_count: int, close_count: int) -> None:
        if len(current) == 2 * n:
            result.append(''.join(current))
            return

        if open_count < n:
            current.append('(')
            backtrack(current, open_count + 1, close_count)
            current.pop()

        if close_count < open_count:
            current.append(')')
            backtrack(current, open_count, close_count + 1)
            current.pop()

    backtrack([], 0, 0)
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: Word Search (DFS + Backtracking)
# ════════════════════════════════════════════════════════════════════════

def exist(board: List[List[str]], word: str) -> bool:
    """
    QUESTION:
    ─────────
    Given an m×n grid of characters and a word, determine if the word
    exists in the grid. The word can be constructed from adjacent cells
    (horizontal or vertical). No cell can be used more than once.

    Example:
        Input: board = [["A","B","C","E"],
                        ["S","F","C","S"],
                        ["A","D","E","E"]],
               word = "ABCCED"
        Output: true

    THOUGHT PROCESS:
    ────────────────
    1. DFS from each cell that matches the first character
    2. At each step, check if current character matches
    3. Mark visited (modify board temporarily) to avoid reuse
    4. Explore 4 directions
    5. Unmark when backtracking
    6. Optimization: Pre-check character frequencies
       (if board has fewer of any char than word needs, return False)
    7. Optimization: if the word's last letter is rarer on the board than
       its first, search for the reversed word (fewer starting points)
    8. Many words at once → Trie + DFS (Trie Q2), not one search per word

    COMPLEXITY:
    ──────────
    Time: O(m × n × 4^L) — L = len(word), 4 branches at each step
    Space: O(L) — Recursion depth
    """
    if not board or not board[0]:
        return False

    rows, cols = len(board), len(board[0])

    # Pruning: character frequency check
    board_counter = Counter()
    for r in range(rows):
        for c in range(cols):
            board_counter[board[r][c]] += 1
    word_counter = Counter(word)
    for char, count in word_counter.items():
        if board_counter[char] < count:
            return False

    def dfs(r: int, c: int, idx: int) -> bool:
        if idx == len(word):
            return True
        if (r < 0 or r >= rows or c < 0 or c >= cols or
                board[r][c] != word[idx]):
            return False

        # Mark visited
        temp, board[r][c] = board[r][c], '#'

        # Explore 4 directions
        found = (dfs(r + 1, c, idx + 1) or
                 dfs(r - 1, c, idx + 1) or
                 dfs(r, c + 1, idx + 1) or
                 dfs(r, c - 1, idx + 1))

        # Unmark (backtrack)
        board[r][c] = temp
        return found

    for r in range(rows):
        for c in range(cols):
            if board[r][c] == word[0] and dfs(r, c, 0):
                return True

    return False


# ════════════════════════════════════════════════════════════════════════
# QUESTION 10: Sudoku Solver
# ════════════════════════════════════════════════════════════════════════

def solve_sudoku(board: List[List[str]]) -> None:
    """
    QUESTION:
    ─────────
    Solve a 9×9 Sudoku by filling empty cells ('.'). Modify in-place.

    THOUGHT PROCESS:
    ────────────────
    1. Find an empty cell, try digits 1-9
    2. For each digit, check if valid (row, col, 3×3 box)
    3. If valid, place digit and recursively solve the rest
    4. If recursive call fails, backtrack (remove digit)
    5. Use sets for O(1) constraint checking
    6. Optimizations (what interviewers probe next):
       - Bit masks instead of sets for row/col/box
       - MRV heuristic: always fill the empty cell with the FEWEST legal
         digits next; it fails fast and prunes enormously
       - Constraint propagation (naked singles) before guessing

    COMPLEXITY:
    ──────────
    Time: O(9^E) worst case for E empty cells; the row/col/box checks
          prune most branches (this code checks constraints but does not
          propagate them)
    Space: O(E) — Recursion stack, E ≤ 81
    """
    rows = [set() for _ in range(9)]
    cols = [set() for _ in range(9)]
    boxes = [set() for _ in range(9)]

    # Initialize constraints from current board
    empty_cells = []
    for r in range(9):
        for c in range(9):
            val = board[r][c]
            if val == '.':
                empty_cells.append((r, c))
            else:
                rows[r].add(val)
                cols[c].add(val)
                boxes[(r // 3) * 3 + c // 3].add(val)

    def backtrack(idx: int) -> bool:
        if idx == len(empty_cells):
            return True

        r, c = empty_cells[idx]
        box_id = (r // 3) * 3 + c // 3

        for digit in '123456789':
            if (digit in rows[r] or digit in cols[c] or digit in boxes[box_id]):
                continue

            # Place digit
            board[r][c] = digit
            rows[r].add(digit)
            cols[c].add(digit)
            boxes[box_id].add(digit)

            if backtrack(idx + 1):
                return True

            # Remove digit (backtrack)
            board[r][c] = '.'
            rows[r].remove(digit)
            cols[c].remove(digit)
            boxes[box_id].remove(digit)

        return False

    backtrack(0)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 11: Letter Combinations of a Phone Number
# ════════════════════════════════════════════════════════════════════════

def letter_combinations(digits: str) -> List[str]:
    """
    QUESTION:
    ─────────
    Given a string of digits 2-9, return all letter combinations they
    could represent on a phone keypad (2 → "abc", ..., 9 → "wxyz").

    Example:
        Input: "23"
        Output: ["ad","ae","af","bd","be","bf","cd","ce","cf"]

    THOUGHT PROCESS:
    ────────────────
    1. Position i has len(mapping[digits[i]]) choices, independent of the
       others → a Cartesian product. Backtracking fills one position per
       recursion level.
    2. No pruning is possible (every path is a valid answer), so this is
       the simplest form of the template; the point is clean
       choose/recurse/un-choose with a shared buffer.
    3. Pythonic equivalent: itertools.product(*(mapping[d] for d in digits))
    4. Empty input → [] (not [""]): a classic edge-case trap.

    COMPLEXITY:
    ──────────
    Time: O(4ⁿ · n) — Up to 4 letters per digit, each result O(n) to join
    Space: O(n) — Recursion depth, excluding output
    """
    if not digits:
        return []

    mapping = {
        "2": "abc", "3": "def", "4": "ghi", "5": "jkl",
        "6": "mno", "7": "pqrs", "8": "tuv", "9": "wxyz",
    }
    result: List[str] = []
    path: List[str] = []

    def backtrack(i: int) -> None:
        if i == len(digits):
            result.append("".join(path))
            return
        for letter in mapping[digits[i]]:
            path.append(letter)        # Choose
            backtrack(i + 1)           # Explore
            path.pop()                 # Un-choose

    backtrack(0)
    return result


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("BACKTRACKING — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Subsets")
    print("-" * 40)
    print(f"   Subsets of [1,2,3]: {subsets([1, 2, 3])}")

    # Q2
    print("\n2️⃣  Subsets II (with Duplicates)")
    print("-" * 40)
    print(f"   Subsets of [1,2,2]: {subsets_with_duplicates([1, 2, 2])}")

    # Q3
    print("\n3️⃣  Permutations")
    print("-" * 40)
    print(f"   Permutations of [1,2,3]: {permute([1, 2, 3])}")

    # Q4
    print("\n4️⃣  Permutations II (with Duplicates)")
    print("-" * 40)
    print(f"   Unique permutations of [1,1,2]: {permute_unique([1, 1, 2])}")

    # Q5
    print("\n5️⃣  Combination Sum")
    print("-" * 40)
    print(f"   candidates=[2,3,6,7], target=7: {combination_sum([2, 3, 6, 7], 7)}")

    # Q6
    print("\n6️⃣  Combination Sum II")
    print("-" * 40)
    print(f"   candidates=[10,1,2,7,6,1,5], target=8: {combination_sum2([10, 1, 2, 7, 6, 1, 5], 8)}")

    # Q7
    print("\n7️⃣  N-Queens")
    print("-" * 40)
    solutions = solve_n_queens(4)
    print(f"   Number of solutions for n=4: {len(solutions)}")
    for sol in solutions:
        print(f"   Solution:")
        for row in sol:
            print(f"     {row}")

    # Q8
    print("\n8️⃣  Generate Parentheses")
    print("-" * 40)
    print(f"   n=3: {generate_parentheses(3)}")

    # Q9
    print("\n9️⃣  Word Search")
    print("-" * 40)
    board = [
        ["A", "B", "C", "E"],
        ["S", "F", "C", "S"],
        ["A", "D", "E", "E"]
    ]
    # Deep copy for demo
    b1 = copy.deepcopy(board)
    b2 = copy.deepcopy(board)
    print(f"   \"ABCCED\": {exist(b1, 'ABCCED')}")
    print(f"   \"SEE\": {exist(b2, 'SEE')}")

    # Q10
    print("\n🔟  Sudoku Solver")
    print("-" * 40)
    sudoku = [
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
    solve_sudoku(sudoku)
    print(f"   Solved board:")
    for row in sudoku:
        print(f"     {' '.join(row)}")

    # Q11
    print("\n1️⃣1️⃣  Letter Combinations of a Phone Number")
    print("-" * 40)
    print(f"   \"23\": {letter_combinations('23')}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
