# Graphs

> Python implementation — 12 questions covering core concepts and interview patterns.

GRAPHS — Core Concepts & Interview Questions

---

```python
"""
GRAPHS — Core Concepts & Interview Questions
=============================================

Core Concepts:
──────────────
• Graph: G = (V, E) — vertices + edges
• Directed vs Undirected, Weighted vs Unweighted, Cyclic vs Acyclic
• Representations: Adjacency Matrix (O(V²) space), Adjacency List (O(V+E) space)
• Connected components, Strongly Connected Components (SCC)
• BFS: Queue-based, shortest path in unweighted graphs, O(V+E)
• DFS: Stack/recursive, connectivity, cycle detection, O(V+E)
• Topological Sort: DAG ordering (Kahn's algorithm: BFS, or DFS with post-order)

Common Patterns:
────────────────
• BFS for shortest path in unweighted graphs
• DFS for connectivity, cycle detection, bipartite check
• Dijkstra for shortest path with positive weights
• Bellman-Ford for negative weights (also detects negative cycles)
• Union-Find (Disjoint Set Union) for dynamic connectivity
• Prim's/Kruskal's for Minimum Spanning Tree
"""

from typing import List, Optional, Tuple, Dict
from collections import deque
import heapq


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Number of Islands (DFS / BFS)
# ════════════════════════════════════════════════════════════════════════

def num_islands(grid: List[List[str]]) -> int:
    """
    QUESTION:
    ─────────
    Given a 2D grid of '1's (land) and '0's (water), count the number of
    islands. An island is surrounded by water and formed by connecting
    adjacent lands horizontally or vertically.

    Example:
        Input: [
            ['1','1','0','0','0'],
            ['1','1','0','0','0'],
            ['0','0','1','0','0'],
            ['0','0','0','1','1']
        ]
        Output: 3

    THOUGHT PROCESS:
    ────────────────
    1. Grid as graph: each cell is a node, edges to adjacent cells
    2. DFS (or BFS) to traverse each connected component
    3. When we find unvisited land, increment count and DFS to mark
       all connected land as visited (sink the island)
    4. In-place modification: change '1' to '0' (or use visited set)

    COMPLEXITY:
    ──────────
    Time: O(m × n) — Visit each cell at most once
    Space: O(m × n) — Worst-case recursion stack for DFS (all land)

    PRODUCTION NOTE:
    ────────────────
    Recursive DFS on a 1000×1000 all-land grid needs a million stack
    frames: Python raises RecursionError (default limit ~1000) and Java
    throws StackOverflowError. Use BFS or an explicit stack when the grid
    can be large. Sinking cells mutates the caller's grid; copy it or use
    a visited set if that matters.
    """
    if not grid:
        return 0

    rows, cols = len(grid), len(grid[0])
    count = 0

    def dfs(r: int, c: int) -> None:
        if r < 0 or r >= rows or c < 0 or c >= cols or grid[r][c] != '1':
            return
        grid[r][c] = '0'  # Mark visited (sink the island)
        dfs(r + 1, c)
        dfs(r - 1, c)
        dfs(r, c + 1)
        dfs(r, c - 1)

    for r in range(rows):
        for c in range(cols):
            if grid[r][c] == '1':
                count += 1
                dfs(r, c)

    return count


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Word Ladder (BFS Shortest Path)
# ════════════════════════════════════════════════════════════════════════

def ladder_length(begin_word: str, end_word: str, word_list: List[str]) -> int:
    """
    QUESTION:
    ─────────
    Given two words and a dictionary, find the length of the shortest
    transformation sequence from beginWord to endWord. Each step changes
    exactly one letter, and intermediate words must be in wordList.

    Example:
        Input: beginWord="hit", endWord="cog", wordList=["hot","dot","dog","lot","log","cog"]
        Output: 5  (hit → hot → dot → dog → cog)

    THOUGHT PROCESS:
    ────────────────
    1. Model as a graph: words are nodes, edges if one letter differs
    2. BFS from beginWord to endWord (shortest path in unweighted graph)
    3. Optimization: Generate all possible transformations (wildcard pattern)
       instead of comparing every pair of words
    4. Wildcard: "hot" → ["*ot", "h*t", "ho*"]
       All words matching a wildcard are neighbors

    5. Mark words visited when ENQUEUED, not when dequeued, or the same
       word is queued many times.
    6. Bidirectional BFS (expand the smaller frontier from both ends)
       cuts the explored states dramatically: roughly b^(d/2) twice
       instead of b^d.

    COMPLEXITY:
    ──────────
    Time: O(m² × n) — n words, m patterns each, each pattern O(m) to build
    Space: O(m² × n) — n·m pattern keys of length m
    """
    if end_word not in set(word_list):
        return 0

    # Build adjacency: wildcard → list of matching words
    neighbors = {}
    for word in word_list:
        for i in range(len(word)):
            pattern = word[:i] + '*' + word[i + 1:]
            neighbors.setdefault(pattern, []).append(word)

    queue = deque([(begin_word, 1)])
    visited = {begin_word}

    while queue:
        current, distance = queue.popleft()
        if current == end_word:
            return distance

        for i in range(len(current)):
            pattern = current[:i] + '*' + current[i + 1:]
            for neighbor in neighbors.get(pattern, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, distance + 1))

    return 0


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Course Schedule (Topological Sort - Kahn's Algorithm)
# ════════════════════════════════════════════════════════════════════════

def can_finish(num_courses: int, prerequisites: List[List[int]]) -> bool:
    """
    QUESTION:
    ─────────
    There are numCourses courses labeled 0 to numCourses-1. You are given
    prerequisites where prerequisites[i] = [a, b] means you must take
    course b before course a. Determine if it's possible to finish all courses.

    Example:
        Input: numCourses = 2, prerequisites = [[1, 0]]
        Output: true  (0 → 1)
        Input: numCourses = 2, prerequisites = [[1, 0], [0, 1]]
        Output: false (cycle: 0 → 1 → 0)

    THOUGHT PROCESS:
    ────────────────
    1. This is cycle detection in a directed graph
    2. Build adjacency list and in-degree array
    3. Kahn's algorithm (BFS topo sort):
       - Start with courses having in-degree 0
       - Process each: decrement neighbors' in-degrees
       - If all courses processed → no cycle
    4. If a cycle exists, some courses will never have in-degree 0

    COMPLEXITY:
    ──────────
    Time: O(V + E) — Build graph + process all edges
    Space: O(V + E) — Adjacency list
    """
    # Build graph
    graph = [[] for _ in range(num_courses)]
    in_degree = [0] * num_courses

    for course, prereq in prerequisites:
        graph[prereq].append(course)
        in_degree[course] += 1

    # Start with courses having no prerequisites
    queue = deque([i for i in range(num_courses) if in_degree[i] == 0])
    processed = 0

    while queue:
        course = queue.popleft()
        processed += 1
        for neighbor in graph[course]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return processed == num_courses


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Course Schedule II (Return Ordering)
# ════════════════════════════════════════════════════════════════════════

def find_order(num_courses: int, prerequisites: List[List[int]]) -> List[int]:
    """
    QUESTION:
    ─────────
    Return the ordering of courses to take to finish all courses.
    If impossible (cycle), return empty array.

    THOUGHT PROCESS:
    ────────────────
    1. Same as can_finish but also track the topological order
    2. Kahn's algorithm naturally produces a valid ordering
    3. DFS alternative: three colours (unvisited / in progress / done);
       reaching an in-progress node means a cycle; the reverse of the
       post-order is a topological order
    4. Need the lexicographically smallest order? Swap the queue for a
       min-heap: O((V + E) log V)

    COMPLEXITY:
    ──────────
    Time: O(V + E)
    Space: O(V + E)
    """
    graph = [[] for _ in range(num_courses)]
    in_degree = [0] * num_courses

    for course, prereq in prerequisites:
        graph[prereq].append(course)
        in_degree[course] += 1

    queue = deque([i for i in range(num_courses) if in_degree[i] == 0])
    order = []

    while queue:
        course = queue.popleft()
        order.append(course)
        for neighbor in graph[course]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return order if len(order) == num_courses else []


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Clone Graph (DFS/BFS)
# ════════════════════════════════════════════════════════════════════════

class GraphNode:
    """Undirected graph node."""
    def __init__(self, val: int = 0):
        self.val = val
        self.neighbors: List['GraphNode'] = []


def clone_graph(node: Optional[GraphNode]) -> Optional[GraphNode]:
    """
    QUESTION:
    ─────────
    Given a reference to a node in a connected undirected graph, return
    a deep copy of the graph.

    THOUGHT PROCESS:
    ────────────────
    1. DFS or BFS to traverse the graph
    2. Use hash map to track cloned nodes (original → clone)
    3. For each node, clone its value and recursively clone neighbors
    4. Hash map prevents infinite loops from cycles

    COMPLEXITY:
    ──────────
    Time: O(V + E) — Visit each node and edge once
    Space: O(V) — Hash map of all nodes
    """
    if not node:
        return None

    clones = {}

    def dfs(original: GraphNode) -> GraphNode:
        if original in clones:
            return clones[original]

        clone = GraphNode(original.val)
        clones[original] = clone

        for neighbor in original.neighbors:
            clone.neighbors.append(dfs(neighbor))

        return clone

    return dfs(node)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Network Delay Time (Dijkstra)
# ════════════════════════════════════════════════════════════════════════

def network_delay_time(times: List[List[int]], n: int, k: int) -> int:
    """
    QUESTION:
    ─────────
    You are given a network of n nodes labeled 1 to n. times[i] = (u, v, w)
    means signal from u takes w time to reach v. Send a signal from node k.
    Return the minimum time for all nodes to receive the signal, or -1 if
    not all nodes can be reached.

    Example:
        Input: times = [[2,1,1],[2,3,1],[3,4,1]], n = 4, k = 2
        Output: 2

    THOUGHT PROCESS:
    ────────────────
    1. This is a shortest path from single source problem
    2. Dijkstra's algorithm (non-negative weights only):
       - Min-heap priority queue: (distance, node)
       - Update distances to neighbors if shorter path found
       - Python's heapq has no decrease-key, so we push duplicates and
         skip "stale" entries whose distance is worse than dist[u]
         ("lazy deletion")
    3. The answer is the maximum distance among all reachable nodes
    4. Why non-negative: once a node is popped, its distance is final
       because any other path is at least as long. One negative edge
       breaks that; use Bellman-Ford (Q11) instead.

    COMPLEXITY:
    ──────────
    Time: O(E log V) — Up to E heap pushes, each O(log E) = O(log V)
    Space: O(V + E) — Adjacency list + distance array + heap
    """
    # Build adjacency list: graph[u] = [(v, w), ...]
    graph = [[] for _ in range(n + 1)]
    for u, v, w in times:
        graph[u].append((v, w))

    # Dijkstra
    dist = [float('inf')] * (n + 1)
    dist[k] = 0
    pq = [(0, k)]  # (distance, node)

    while pq:
        d, u = heapq.heappop(pq)
        if d > dist[u]:
            continue  # Stale entry
        for v, w in graph[u]:
            if dist[u] + w < dist[v]:
                dist[v] = dist[u] + w
                heapq.heappush(pq, (dist[v], v))

    # Max distance among reachable nodes
    max_dist = max(dist[1:])
    return -1 if max_dist == float('inf') else max_dist


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Union Find (Disjoint Set Union)
# ════════════════════════════════════════════════════════════════════════

class UnionFind:
    """
    QUESTION:
    ─────────
    Implement Union-Find data structure with path compression and union
    by rank for efficient dynamic connectivity queries.

    Used in: Number of Provinces, Accounts Merge, Redundant Connection

    THOUGHT PROCESS:
    ────────────────
    1. Each element starts as its own parent (self-loop)
    2. find(x): recursively find the root of x
       - With path compression: set parent to root (flattens tree)
    3. union(x, y): connect the sets containing x and y
       - With union by rank: attach the root of LOWER rank under the
         higher one. Rank is an upper bound on tree height; it is not
         updated by path compression. (Union by size works equally well
         and also gives you component sizes.)
    4. connected(x, y): check if x and y have same root
    5. Either optimisation alone gives O(log n); both together give
       O(α(n)) amortized. With union by rank the tree height is at most
       log n, so the recursive find cannot hit Python's recursion limit.
    6. Limitation: no efficient "split"/delete. For deletions, process
       edges offline in reverse, or use other structures.

    COMPLEXITY:
    ──────────
    Time: O(α(n)) amortized per operation — inverse Ackermann, ≤ 4 for
          any realistic n
    Space: O(n) — Parent and rank arrays
    """

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n
        self.components = n  # Number of connected components

    def find(self, x: int) -> int:
        # Path compression: make x point directly to root
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> bool:
        root_x, root_y = self.find(x), self.find(y)
        if root_x == root_y:
            return False  # Already connected

        # Union by rank: attach smaller tree under larger root
        if self.rank[root_x] < self.rank[root_y]:
            self.parent[root_x] = root_y
        elif self.rank[root_x] > self.rank[root_y]:
            self.parent[root_y] = root_x
        else:
            self.parent[root_y] = root_x
            self.rank[root_x] += 1

        self.components -= 1
        return True

    def connected(self, x: int, y: int) -> bool:
        return self.find(x) == self.find(y)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Number of Provinces (Union Find / DFS)
# ════════════════════════════════════════════════════════════════════════

def find_circle_num(is_connected: List[List[int]]) -> int:
    """
    QUESTION:
    ─────────
    There are n cities. isConnected[i][j] = 1 means city i and j are
    directly connected. A province is a group of directly or indirectly
    connected cities. Return the total number of provinces.

    Example:
        Input: [[1,1,0],[1,1,0],[0,0,1]]
        Output: 2

    THOUGHT PROCESS:
    ────────────────
    1. This is finding connected components in an undirected graph
    2. Union Find: union connected cities, count distinct roots
    3. DFS: For each unvisited city, DFS to mark all connected cities

    COMPLEXITY:
    ──────────
    Time: O(n²) — Upper triangular matrix scan
    Space: O(n) — Union Find parent array
    """
    n = len(is_connected)
    uf = UnionFind(n)

    for i in range(n):
        for j in range(i + 1, n):
            if is_connected[i][j]:
                uf.union(i, j)

    return uf.components


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: Pacific Atlantic Water Flow
# ════════════════════════════════════════════════════════════════════════

def pacific_atlantic(heights: List[List[int]]) -> List[List[int]]:
    """
    QUESTION:
    ─────────
    Given a matrix of heights, water flows from a cell to adjacent cells
    with equal or lower height. The Pacific touches left & top edges,
    Atlantic touches right & bottom edges. Return cells where water can
    flow to both oceans.

    THOUGHT PROCESS:
    ────────────────
    1. Reverse thinking: Instead of going from each cell to ocean,
       start from ocean boundaries and flow INWARD to higher cells
    2. Two DFS passes: mark cells reachable from Pacific, then Atlantic
    3. Cells in both sets are the answer
    4. Flow condition: From ocean, we can go to cells with height ≥ current

    COMPLEXITY:
    ──────────
    Time: O(m × n) — Each cell visited twice (Pacific + Atlantic)
    Space: O(m × n) — Two boolean matrices (+ recursion depth; use an
           explicit stack/BFS for large grids)
    """
    if not heights:
        return []

    rows, cols = len(heights), len(heights[0])
    pacific = [[False] * cols for _ in range(rows)]
    atlantic = [[False] * cols for _ in range(rows)]

    def dfs(r: int, c: int, ocean: List[List[bool]]) -> None:
        ocean[r][c] = True
        for dr, dc in [(1, 0), (-1, 0), (0, 1), (0, -1)]:
            nr, nc = r + dr, c + dc
            if (0 <= nr < rows and 0 <= nc < cols and
                not ocean[nr][nc] and heights[nr][nc] >= heights[r][c]):
                dfs(nr, nc, ocean)

    # From Pacific edges (top and left)
    for c in range(cols):
        dfs(0, c, pacific)
    for r in range(rows):
        dfs(r, 0, pacific)

    # From Atlantic edges (bottom and right)
    for c in range(cols):
        dfs(rows - 1, c, atlantic)
    for r in range(rows):
        dfs(r, cols - 1, atlantic)

    # Cells reachable from both oceans
    result = []
    for r in range(rows):
        for c in range(cols):
            if pacific[r][c] and atlantic[r][c]:
                result.append([r, c])

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 10: Alien Dictionary (Topological Sort)
# ════════════════════════════════════════════════════════════════════════

def alien_order(words: List[str]) -> str:
    """
    QUESTION:
    ─────────
    Given a sorted dictionary of an alien language, find the order of
    characters. Words are sorted lexicographically in the alien language.

    Example:
        Input: ["wrt","wrf","er","ett","rftt"]
        Output: "wertf"

    THOUGHT PROCESS:
    ────────────────
    1. Compare adjacent words to find character precedence
       - "wrt" before "wrf": t comes before f
       - "er" before "ett": r comes before t
    2. Build graph from these precedence relations
    3. Topological sort (Kahn's algorithm) to find character order
    4. Edge cases: "abc" before "ab" → invalid (prefix issue)
    5. Only the FIRST differing character of each adjacent pair gives
       information; everything after it says nothing about order.
    6. Letters that appear but have no constraints can go anywhere, so
       several outputs may be valid.

    COMPLEXITY:
    ──────────
    Time: O(C) — C = total characters across all words
    Space: O(1) — At most 26 unique characters (26² edges)
    """
    # Initialize graph
    graph = {c: set() for word in words for c in word}
    in_degree = {c: 0 for c in graph}

    # Build edges from adjacent word comparisons
    for i in range(len(words) - 1):
        w1, w2 = words[i], words[i + 1]
        shorter = min(len(w1), len(w2))

        # Invalid case: "abc" before "ab"
        if len(w1) > len(w2) and w1[:shorter] == w2[:shorter]:
            return ""

        for j in range(shorter):
            if w1[j] != w2[j]:
                if w2[j] not in graph[w1[j]]:
                    graph[w1[j]].add(w2[j])
                    in_degree[w2[j]] = in_degree.get(w2[j], 0) + 1
                break

    # Kahn's algorithm
    queue = deque([c for c in graph if in_degree[c] == 0])
    order = []

    while queue:
        c = queue.popleft()
        order.append(c)
        for neighbor in graph[c]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(graph):
        return ""  # Cycle detected

    return ''.join(order)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 11: Cheapest Flights Within K Stops (Bellman-Ford)
# ════════════════════════════════════════════════════════════════════════

def find_cheapest_price(n: int, flights: List[List[int]], src: int, dst: int, k: int) -> int:
    """
    QUESTION:
    ─────────
    n cities, flights[i] = [from, to, price]. Return the cheapest price
    from src to dst using at most k stops (k + 1 edges), or -1.

    Example:
        Input: n=4, flights=[[0,1,100],[1,2,100],[2,0,100],[1,3,600],[2,3,200]],
               src=0, dst=3, k=1
        Output: 700  (0 → 1 → 3; 0 → 1 → 2 → 3 costs 400 but has 2 stops)

    THOUGHT PROCESS:
    ────────────────
    1. Plain Dijkstra is wrong here: it finalizes the cheapest route to a
       node even if that route used too many stops, and may discard a
       pricier route that had stops left.
    2. Bellman-Ford fits the constraint exactly: after round i, prices[v]
       is the cheapest cost using at most i edges. Run k + 1 rounds.
    3. Each round must read from the PREVIOUS round's prices (copy the
       array). Relaxing in place could chain two edges in one round and
       silently exceed the stop limit.
    4. General Bellman-Ford: V - 1 rounds give shortest paths with
       negative edges allowed; if a V-th round still relaxes an edge,
       there is a negative cycle reachable from the source.
    5. Alternatives: BFS by levels with pruning, or Dijkstra on states
       (node, stops_used).

    COMPLEXITY:
    ──────────
    Time: O(k · E) — k + 1 rounds over all edges (general BF: O(V · E))
    Space: O(V) — Two price arrays
    """
    INF = float("inf")
    prices = [INF] * n
    prices[src] = 0

    for _ in range(k + 1):
        nxt = prices[:]                       # Read old, write new
        for u, v, w in flights:
            if prices[u] != INF and prices[u] + w < nxt[v]:
                nxt[v] = prices[u] + w
        prices = nxt

    return -1 if prices[dst] == INF else prices[dst]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 12: Min Cost to Connect All Points (MST — Kruskal / Prim)
# ════════════════════════════════════════════════════════════════════════

def min_cost_connect_points(points: List[List[int]]) -> int:
    """
    QUESTION:
    ─────────
    Given points on a 2-D plane, the cost to connect two points is their
    Manhattan distance. Return the minimum cost to connect all points
    (a minimum spanning tree over the complete graph).

    Example:
        Input: [[0,0],[2,2],[3,10],[5,2],[7,0]]
        Output: 20

    THOUGHT PROCESS:
    ────────────────
    1. "Connect everything at minimum total cost" = MST.
    2. Kruskal: sort all edges by weight, add each edge unless it joins
       two nodes already connected (Union-Find, Q7). Stop at V - 1 edges.
       O(E log E). Best for sparse graphs given as an edge list.
    3. Prim: grow one tree from any node, always adding the cheapest edge
       leaving it. With a heap: O(E log V). On a dense / complete graph
       the array version (implemented below) is O(V²) with no heap and no
       edge list, which beats Kruskal's O(V² log V) here.
    4. Both are greedy and correct by the cut property: the lightest edge
       crossing any cut belongs to some MST.

    COMPLEXITY:
    ──────────
    Time: O(V²) — V iterations, each scanning all V points
    Space: O(V) — min_cost and in_tree arrays
    """
    n = len(points)
    if n <= 1:
        return 0

    in_tree = [False] * n
    min_cost = [float("inf")] * n     # Cheapest edge from tree to node i
    min_cost[0] = 0
    total = 0

    for _ in range(n):
        # Pick the cheapest point not yet in the tree
        u = min((i for i in range(n) if not in_tree[i]), key=min_cost.__getitem__)
        in_tree[u] = True
        total += min_cost[u]
        ux, uy = points[u]
        for v in range(n):
            if not in_tree[v]:
                d = abs(ux - points[v][0]) + abs(uy - points[v][1])
                if d < min_cost[v]:
                    min_cost[v] = d

    return total


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("GRAPHS — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Number of Islands")
    print("-" * 40)
    grid = [
        ['1','1','0','0','0'],
        ['1','1','0','0','0'],
        ['0','0','1','0','0'],
        ['0','0','0','1','1']
    ]
    # Deep copy for demo
    grid_copy = [row[:] for row in grid]
    print(f"   Islands: {num_islands(grid_copy)}")

    # Q2
    print("\n2️⃣  Word Ladder")
    print("-" * 40)
    begin, end = "hit", "cog"
    words = ["hot", "dot", "dog", "lot", "log", "cog"]
    print(f"   {begin} → {end}: {ladder_length(begin, end, words)} steps")

    # Q3
    print("\n3️⃣  Course Schedule")
    print("-" * 40)
    print(f"   2 courses, [[1,0]]: {can_finish(2, [[1, 0]])}")
    print(f"   2 courses, [[1,0],[0,1]]: {can_finish(2, [[1, 0], [0, 1]])}")

    # Q4
    print("\n4️⃣  Course Schedule II")
    print("-" * 40)
    print(f"   Order: {find_order(4, [[1,0],[2,0],[3,1],[3,2]])}")

    # Q5
    print("\n5️⃣  Clone Graph")
    print("-" * 40)
    a, b, c = GraphNode(1), GraphNode(2), GraphNode(3)
    a.neighbors, b.neighbors, c.neighbors = [b, c], [a, c], [a, b]
    a2 = clone_graph(a)
    print(f"   Triangle 1-2-3 cloned; clone of 1 has neighbours "
          f"{[n.val for n in a2.neighbors]}, new object: {a2 is not a}")

    # Q6
    print("\n6️⃣  Network Delay Time (Dijkstra)")
    print("-" * 40)
    times = [[2, 1, 1], [2, 3, 1], [3, 4, 1]]
    print(f"   Network: {times}, n=4, k=2")
    print(f"   Delay time: {network_delay_time(times, 4, 2)}")

    # Q7
    print("\n7️⃣  Union Find")
    print("-" * 40)
    uf = UnionFind(5)
    uf.union(0, 1)
    uf.union(1, 2)
    uf.union(3, 4)
    print(f"   After unions (0-1-2) and (3-4):")
    print(f"   connected(0, 2): {uf.connected(0, 2)}")
    print(f"   connected(0, 3): {uf.connected(0, 3)}")
    print(f"   components: {uf.components}")

    # Q8
    print("\n8️⃣  Number of Provinces")
    print("-" * 40)
    is_connected = [[1, 1, 0], [1, 1, 0], [0, 0, 1]]
    print(f"   Provinces: {find_circle_num(is_connected)}")

    # Q9
    print("\n9️⃣  Pacific Atlantic Water Flow")
    print("-" * 40)
    heights = [
        [1, 2, 2, 3, 5],
        [3, 2, 3, 4, 4],
        [2, 4, 5, 3, 1],
        [6, 7, 1, 4, 5],
        [5, 1, 1, 2, 4]
    ]
    result = pacific_atlantic(heights)
    print(f"   Cells flowing to both oceans: {result}")

    # Q10
    print("\n🔟  Alien Dictionary")
    print("-" * 40)
    alien_words = ["wrt", "wrf", "er", "ett", "rftt"]
    print(f"   Words: {alien_words}")
    print(f"   Order: \"{alien_order(alien_words)}\"")

    # Q11
    print("\n1️⃣1️⃣  Cheapest Flights Within K Stops (Bellman-Ford)")
    print("-" * 40)
    flights = [[0, 1, 100], [1, 2, 100], [2, 0, 100], [1, 3, 600], [2, 3, 200]]
    print(f"   0 → 3 with k=1: {find_cheapest_price(4, flights, 0, 3, 1)}")
    print(f"   0 → 3 with k=2: {find_cheapest_price(4, flights, 0, 3, 2)}")

    # Q12
    print("\n1️⃣2️⃣  Min Cost to Connect All Points (MST)")
    print("-" * 40)
    pts = [[0, 0], [2, 2], [3, 10], [5, 2], [7, 0]]
    print(f"   Points: {pts}")
    print(f"   MST cost: {min_cost_connect_points(pts)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()

```

---

[← Back to DSA Overview](../index.md)
