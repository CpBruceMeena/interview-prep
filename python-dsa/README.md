# Python Data Structures & Algorithms — Interview Preparation

> Data Structures and Algorithms implemented in Python for interview preparation. Each category covers core concepts, common interview questions, the thought process behind each solution, and complexity analysis. Every file runs as a script, and the solutions were cross-checked against brute-force implementations on randomized inputs.

---

## 📚 Categories

| # | Category | Qs | Key Topics |
|---|----------|----|------------|
| 01 | [Arrays](./01_arrays/questions.py) | 12 | Hash-map complement, Kadane, prefix/suffix products, two pointers, intervals, cyclic sort, trapping rain water |
| 02 | [Strings](./02_strings/questions.py) | 10 | Sliding window, palindromes (center expansion, Manacher), anagrams, atoi overflow, encode/decode |
| 03 | [Stacks](./03_stacks/questions.py) | 9 | Monotonic stack, min stack, RPN and Basic Calculator, histogram, decode string |
| 04 | [Queues](./04_queues/questions.py) | 7 | Monotonic deque, circular buffer, queue ↔ stack, task scheduler, multi-source BFS |
| 05 | [Hashing](./05_hashing/questions.py) | 9 | Prefix sum + hash map, frequency counting, top-k, LRU via OrderedDict, designing a hash map |
| 06 | [Linked Lists](./06_linked_lists/questions.py) | 10 | Reversal (incl. k-group), Floyd's cycle detection, merge, fast/slow pointers, deep copy with random pointers |
| 07 | [Trees](./07_trees/questions.py) | 12 | Traversals, BST validation, LCA, serialization, diameter, max path sum, build from traversals |
| 08 | [Graphs](./08_graphs/questions.py) | 12 | BFS/DFS, topological sort, Dijkstra, Bellman-Ford, Union-Find, MST (Prim/Kruskal) |
| 09 | [Dynamic Programming](./09_dynamic_programming/questions.py) | 13 | Memoization vs tabulation, coin change, knapsack, LIS, LCS, edit distance, word break, decode ways |
| 10 | [Sorting & Searching](./10_sorting_searching/questions.py) | 11 | Quick/merge/heap sort, quickselect, binary search variants, search on the answer, median of two arrays |
| 11 | [Backtracking](./11_backtracking/questions.py) | 11 | Subsets, permutations, combinations (with duplicates), N-Queens, Sudoku, word search |
| 12 | [Trie](./12_trie/questions.py) | 7 | Prefix tree, Word Search II, wildcard search, autocomplete, concatenated words |
| 13 | [Heaps](./13_heaps/questions.py) | 9 | Top-k, merge k lists, two-heap median (stream and sliding window), meeting rooms, job scheduling |
| 14 | [Bit Manipulation](./14_bit_manipulation/questions.py) | 10 | XOR tricks, popcount, power of two, 32-bit emulation in Python, max XOR with a bit trie |
| 15 | [Advanced Strings](./15_advanced_strings/questions.py) | 8 | KMP, Rabin-Karp, Z-algorithm, Manacher, suffix array + LCP (Kasai) |
| 16 | [Advanced Trees](./16_advanced_trees/questions.py) | 4 | AVL (insert/delete), Red-Black (insert), B-Tree (insert), B+ Tree and database indexes |
| 17 | [Sliding Window](./17_sliding_window/questions.py) | 9 | Variable/fixed windows, at-most-K and exactly-K, permutation in string, min window subsequence |
| 18 | [Greedy](./18_greedy/questions.py) | 9 | Activity selection, Huffman coding, jump game, gas station, interval scheduling, candy, task scheduler |
| 19 | [Math & Number Theory](./19_math_number_theory/questions.py) | 10 | Sieve (incl. segmented), GCD/LCM, fast modular exponentiation, factorization, reservoir sampling |
| 20 | [Design Problems](./20_design_problems/questions.py) | 8 | Logger, rate limiter, elevator, pub-sub, thread pool, URL shortener, LRU and LFU cache |

**190 questions across 20 categories.** "Qs" is the number of `# QUESTION n` / `# DESIGN n` banners in each file (Advanced Trees counts its four structures); `scripts/generate_dsa_docs.py` derives the site's counts the same way.

---|----------|------------|------|
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
| 18 | [Greedy](./18_greedy/questions.py) | Activity selection, Huffman, jump game, gas station, partition | `questions.py` |
| 19 | [Math & Number Theory](./19_math_number_theory/questions.py) | Sieve, GCD/LCM, modular exp, prime factors, reservoir sampling | `questions.py` |
| 20 | [Design Problems](./20_design_problems/questions.py) | Logger, rate limiter, elevator, pub-sub, thread pool, URL shortener | `questions.py` |

---

## 🎯 How to Use

```bash
# Run all demos (exits non-zero if any category fails)
python3 python-dsa/main.py

# List categories
python3 python-dsa/main.py -l

# Run a specific category
python3 python-dsa/01_arrays/questions.py
python3 python-dsa/03_stacks/questions.py
```

Requires Python 3.9+ (no third-party packages). The site pages under `docs/python-dsa/` are generated from these files with `python3 scripts/generate_dsa_docs.py`; edit the `.py` files, not the generated pages.

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
- Negative numbers, duplicates, overflow (Python ints never overflow, but
  Java/Go `int` does: say how you'd handle it)
- Large inputs (performance testing, recursion depth: Python's default
  limit is ~1000 frames)

---

## ⚡ Quick Reference: Time Complexities

| Structure | Access | Search | Insertion | Deletion |
|-----------|--------|--------|-----------|----------|
| Array (dynamic) | O(1) | O(n) | O(n); O(1) amortized append | O(n); O(1) at end |
| Stack | O(n) | O(n) | O(1)* | O(1)* |
| Queue | O(n) | O(n) | O(1)* | O(1)* |
| Linked List | O(n) | O(n) | O(1)‡ | O(1)‡ |
| Hash Table | N/A | O(1) avg, O(n) worst | O(1) avg | O(1) avg |
| BST (balanced) | O(log n) | O(log n) | O(log n) | O(log n) |
| BST (unbalanced) | O(n) worst | O(n) worst | O(n) worst | O(n) worst |
| Heap | O(1)† | O(n) | O(log n) | O(log n)† |

*At ends only. †Min/max only (deleting an arbitrary element needs its index). ‡Given a reference to the node (or its predecessor for a singly linked list); finding it is O(n).

---

## 🏆 Key DSA Patterns Cheatsheet

| Pattern | When to Use | Example |
|---------|-------------|---------|
| **Two Pointers** | Sorted array, palindrome | Pair with target sum |
| **Sliding Window** | Contiguous subarray/substring, monotonic condition | Longest substring without repeating |
| **Prefix Sum** | Range sums; subarray sums with negatives | Subarray sum equals k |
| **Monotonic Stack** | Next greater/smaller element | Daily temperatures |
| **Slow/Fast Pointers** | Cycle detection, middle of list | Linked list cycle |
| **BFS** | Shortest path, level order | Word ladder |
| **DFS** | Exhaustive search, path finding | Number of islands |
| **Binary Search** | Sorted data, "find the boundary", monotonic answer | Search in rotated array, Koko eating bananas |
| **Topological Sort** | Dependency ordering | Course schedule |
| **Union Find** | Connected components | Number of provinces |
| **Heap / Top-K** | Repeated min/max, k best, merging sorted streams | Merge k lists, median of stream |
| **DP: Memoization** | Overlapping subproblems | Fibonacci, coin change |
| **DP: Tabulation** | Bottom-up optimal | Knapsack, LCS |
| **Backtracking** | All permutations/combinations | N-Queens |
| **Greedy** | Local choice provably safe (exchange argument) | Activity selection |

---

> **Pro Tip**: Focus on recognizing patterns rather than memorizing solutions. Most interview problems are variations of these core patterns with added twists.
