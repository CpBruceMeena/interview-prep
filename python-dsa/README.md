# Python Data Structures & Algorithms — Interview Preparation

> A comprehensive collection of Data Structures and Algorithms implemented in Python, designed for interview preparation. Each category covers core concepts, common interview questions, thought process behind solutions, and complexity analysis.

---

## 📚 Categories

| # | Category | Key Topics | File |
|---|----------|------------|------|
| 01 | [Arrays](./01_arrays/questions.py) | Two pointers, sliding window, prefix sum, subarray problems | `questions.py` |
| 02 | [Strings](./02_strings/questions.py) | Pattern matching, palindromes, anagrams, string manipulation | `questions.py` |
| 03 | [Stacks](./03_stacks/questions.py) | Monotonic stack, expression evaluation, next greater element | `questions.py` |
| 04 | [Queues](./04_queues/questions.py) | BFS, sliding window max, circular queue, deques | `questions.py` |
| 05 | [Hashing](./05_hashing/questions.py) | Frequency maps, set operations, two-sum variants, caching | `questions.py` |
| 06 | [Linked Lists](./06_linked_lists/questions.py) | Reversal, cycle detection, merge, intersection, LRU cache | `questions.py` |
| 07 | [Trees](./07_trees/questions.py) | BST, traversals, LCA, path sum, serialization | `questions.py` |
| 08 | [Graphs](./08_graphs/questions.py) | BFS, DFS, shortest path, topological sort, union find | `questions.py` |
| 09 | [Dynamic Programming](./09_dynamic_programming/questions.py) | Memoization, tabulation, knapsack, LCS, LIS | `questions.py` |
| 10 | [Sorting & Searching](./10_sorting_searching/questions.py) | Quick sort, merge sort, binary search variants | `questions.py` |
| 11 | [Backtracking](./11_backtracking/questions.py) | N-Queens, subsets, permutations, combinations, Sudoku | `questions.py` |
| 12 | [Trie](./12_trie/questions.py) | Prefix tree, word search, autocomplete, wildcard search | `questions.py` |
| 13 | [Heaps](./13_heaps/questions.py) | Priority queue, median, merged k lists, top k, task scheduler | `questions.py` |
| 14 | [Bit Manipulation](./14_bit_manipulation/questions.py) | XOR tricks, counting bits, single number, power of two | `questions.py` |
| 15 | [Advanced Strings](./15_advanced_strings/questions.py) | KMP, Rabin-Karp, Z-Algorithm, Manacher's, suffix array | `questions.py` |
| 16 | [Advanced Trees](./16_advanced_trees/questions.py) | AVL, Red-Black, B-Tree, B+ Tree, rotations | `questions.py` |
| 17 | [Sliding Window](./17_sliding_window/questions.py) | Variable/fixed window, substring, subarray, two pointers | `questions.py` |

---

## 🎯 How to Use

```bash
# Run all demos
python python-dsa/main.py

# Run a specific category
python python-dsa/01_arrays/questions.py
python python-dsa/03_stacks/questions.py
```

---

## 📖 Question Format

Every question in this collection follows a consistent structure:

```python
def solve_problem(input_data) -> Output:
    """
    QUESTION:
    ─────────
    Problem statement with constraints

    THOUGHT PROCESS:
    ────────────────
    Step-by-step reasoning from brute force to optimal solution

    APPROACH:
    ────────
    Detailed explanation of the chosen approach

    COMPLEXITY:
    ──────────
    Time Complexity: O(?) — Explanation
    Space Complexity: O(?) — Explanation

    EDGE CASES:
    ──────────
    • Empty input
    • Single element
    • Duplicates
    • Negative numbers
    """
    pass
```

---

## 🧠 Core DSA Problem-Solving Framework

### Step 1: Understand the Problem
- **Input/Output**: What are the exact types and constraints?
- **Brute Force First**: What's the naive solution?
- **Optimization Goals**: Time vs Space trade-offs

### Step 2: Identify the Pattern
- **Array/Linear Scan** — Two pointers, sliding window, prefix sum
- **String Manipulation** — Hashing, palindrome expansion
- **Stack/Queue** — Monotonic properties, BFS
- **Hashing** — Frequency counting, caching
- **Linked List** — Slow/fast pointers, reversal
- **Tree/Graph** — Recursive traversal, level-order, shortest path
- **DP** — Overlapping subproblems, optimal substructure
- **Sort/Search** — Binary search on answer, partitioning

### Step 3: Analyze Complexity
- **Time**: How does runtime scale with input?
- **Space**: What additional memory is needed?
- **Trade-offs**: Can we trade space for time?

### Step 4: Test Edge Cases
- Empty input, single element, all same, already sorted
- Negative numbers, duplicates, overflow
- Large inputs (performance testing)

---

## ⚡ Quick Reference: Time Complexities

| Structure | Access | Search | Insertion | Deletion |
|-----------|--------|--------|-----------|----------|
| Array | O(1) | O(n) | O(n) | O(n) |
| Stack | O(n) | O(n) | O(1)* | O(1)* |
| Queue | O(n) | O(n) | O(1)* | O(1)* |
| Linked List | O(n) | O(n) | O(1) | O(1) |
| Hash Table | N/A | O(1) | O(1) | O(1) |
| BST (balanced) | O(log n) | O(log n) | O(log n) | O(log n) |
| Heap | O(1)† | O(n) | O(log n) | O(log n) |

*At ends only. †Min/Max only.

---

## 🏆 Key DSA Patterns Cheatsheet

| Pattern | When to Use | Example |
|---------|-------------|---------|
| **Two Pointers** | Sorted array, palindrome | Pair with target sum |
| **Sliding Window** | Contiguous subarray/substring | Longest substring without repeating |
| **Prefix Sum** | Range sum queries | Subarray sum equals k |
| **Monotonic Stack** | Next greater/smaller element | Daily temperatures |
| **Slow/Fast Pointers** | Cycle detection, middle of list | Linked list cycle |
| **BFS** | Shortest path, level order | Word ladder |
| **DFS** | Exhaustive search, path finding | Number of islands |
| **Binary Search** | Sorted data, "find the boundary" | Search in rotated array |
| **Topological Sort** | Dependency ordering | Course schedule |
| **Union Find** | Connected components | Number of provinces |
| **DP: Memoization** | Overlapping subproblems | Fibonacci, coin change |
| **DP: Tabulation** | Bottom-up optimal | Knapsack, LCS |
| **Backtracking** | All permutations/combinations | N-Queens |
| **Greedy** | Local optimum = global optimum | Activity selection |

---

> **Pro Tip**: Focus on recognizing patterns rather than memorizing solutions. Most interview problems are variations of these core patterns with added twists.
