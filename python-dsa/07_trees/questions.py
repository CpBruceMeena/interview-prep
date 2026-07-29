"""
TREES — Core Concepts & Interview Questions
============================================

Core Concepts:
──────────────
• Binary Tree: Each node has at most 2 children (left, right)
• Binary Search Tree (BST): left < root < right — enables O(log n) search
• Tree traversals: Preorder (root-L-R), Inorder (L-root-R), Postorder (L-R-root)
• BFS (Level Order): Queue-based, processes level by level
• DFS: Stack-based (or recursive), goes deep before wide
• Balanced trees: AVL, Red-Black — height = O(log n)
• Complete vs Full vs Perfect binary trees

Common Patterns:
────────────────
• Recursive divide and conquer
• Level-order traversal (BFS with queue)
• Lowest Common Ancestor (LCA)
• Serialize / Deserialize
• BST validation (inorder traversal check)
• Path sum problems
"""

from typing import List, Optional, Tuple
from collections import deque


class TreeNode:
    """Binary tree node."""
    def __init__(self, val: int = 0, left: Optional['TreeNode'] = None, right: Optional['TreeNode'] = None):
        self.val = val
        self.left = left
        self.right = right


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Binary Tree Traversals (Recursive & Iterative)
# ════════════════════════════════════════════════════════════════════════

def inorder_traversal(root: Optional[TreeNode]) -> List[int]:
    """
    QUESTION:
    ─────────
    Perform inorder traversal of a binary tree. For BST, this gives
    sorted order.

    THOUGHT PROCESS:
    ────────────────
    1. Recursive: left → root → right — O(n) time, O(h) space (stack)
    2. Iterative: Use stack to simulate recursion
       - Go left as far as possible, pushing nodes
       - Pop, visit, then go right
    3. Morris Traversal: Use threaded pointers for O(1) space

    COMPLEXITY:
    ──────────
    Time: O(n) — Visit each node once
    Space: O(h) — Stack height = tree height (h = n for skewed tree)
    """
    result = []
    stack = []
    current = root

    while current or stack:
        # Go as far left as possible
        while current:
            stack.append(current)
            current = current.left

        # Pop and visit
        current = stack.pop()
        result.append(current.val)

        # Go right
        current = current.right

    return result


def preorder_traversal(root: Optional[TreeNode]) -> List[int]:
    """
    Preorder: root → left → right. Used for copying/tree serialization.
    Time: O(n), Space: O(h)
    """
    if not root:
        return []

    result = []
    stack = [root]

    while stack:
        node = stack.pop()
        result.append(node.val)
        # Push right first so left is processed first (LIFO)
        if node.right:
            stack.append(node.right)
        if node.left:
            stack.append(node.left)

    return result


def postorder_traversal(root: Optional[TreeNode]) -> List[int]:
    """
    Postorder: left → right → root. Used for tree deletion.
    Time: O(n), Space: O(h)
    """
    if not root:
        return []

    result = []
    stack = [(root, False)]

    while stack:
        node, visited = stack.pop()
        if visited:
            result.append(node.val)
        else:
            stack.append((node, True))
            if node.right:
                stack.append((node.right, False))
            if node.left:
                stack.append((node.left, False))

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Level Order Traversal (BFS)
# ════════════════════════════════════════════════════════════════════════

def level_order(root: Optional[TreeNode]) -> List[List[int]]:
    """
    QUESTION:
    ─────────
    Return the level order traversal of a binary tree (left to right,
    level by level).

    Example:
        Input: Tree: 3 → (9, 20 → (15, 7))
        Output: [[3], [9, 20], [15, 7]]

    THOUGHT PROCESS:
    ────────────────
    1. Use a queue for BFS
    2. Process one level at a time: get queue size, process that many nodes
    3. For each node, add its children to the queue
    4. The "size" technique ensures we know level boundaries

    COMPLEXITY:
    ──────────
    Time: O(n) — Visit each node once
    Space: O(w) — Queue width = max level width (up to n/2)
    """
    if not root:
        return []

    result = []
    queue = deque([root])

    while queue:
        level_size = len(queue)
        level = []

        for _ in range(level_size):
            node = queue.popleft()
            level.append(node.val)
            if node.left:
                queue.append(node.left)
            if node.right:
                queue.append(node.right)

        result.append(level)

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Validate Binary Search Tree
# ════════════════════════════════════════════════════════════════════════

def is_valid_bst(root: Optional[TreeNode]) -> bool:
    """
    QUESTION:
    ─────────
    Given the root of a binary tree, determine if it is a valid BST.
    A valid BST: left subtree < root < right subtree (recursively).

    Example:
        Input: 2 → (1, 3)
        Output: true
        Input: 5 → (1, 4 → (3, 6))
        Output: false

    THOUGHT PROCESS:
    ────────────────
    1. Naive: Check if left < root and right > root — WRONG!
       Need ALL nodes in left subtree < root, not just immediate child
    2. Approach 1: Inorder traversal should be strictly increasing
       (for BST, inorder gives sorted order)
    3. Approach 2: Recursive with min/max bounds
       - For each node, keep a valid range (low, high)
       - Left child must be in (low, root.val)
       - Right child must be in (root.val, high)

    COMPLEXITY:
    ──────────
    Time: O(n) — Visit each node once
    Space: O(h) — Recursion stack
    """

    def validate(node: Optional[TreeNode], low: float, high: float) -> bool:
        if not node:
            return True
        if node.val <= low or node.val >= high:
            return False
        return (validate(node.left, low, node.val) and
                validate(node.right, node.val, high))

    return validate(root, float('-inf'), float('inf'))


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Maximum Depth of Binary Tree
# ════════════════════════════════════════════════════════════════════════

def max_depth(root: Optional[TreeNode]) -> int:
    """
    QUESTION:
    ─────────
    Given the root, find its maximum depth (number of nodes along the
    longest path from root to farthest leaf).

    THOUGHT PROCESS:
    ────────────────
    1. Recursive: max_depth = 1 + max(left_depth, right_depth)
    2. This is a classic divide-and-conquer problem
    3. Bottom-up: compute subtree depths, combine at parent
    4. Top-down: track depth while traversing, update global max

    COMPLEXITY:
    ──────────
    Time: O(n) — Visit each node
    Space: O(h) — Recursion stack
    """
    if not root:
        return 0
    return 1 + max(max_depth(root.left), max_depth(root.right))


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Lowest Common Ancestor (BST)
# ════════════════════════════════════════════════════════════════════════

def lowest_common_ancestor_bst(root: Optional[TreeNode], p: TreeNode, q: TreeNode) -> Optional[TreeNode]:
    """
    QUESTION:
    ─────────
    Given a BST, find the lowest common ancestor of two nodes.

    Example:
        Input: BST root=6, p=2, q=8
        Output: 6

    THOUGHT PROCESS:
    ────────────────
    1. BST property: left < root < right
    2. If p and q are on different sides of root → root is LCA
    3. If both are smaller → LCA is in left subtree
    4. If both are larger → LCA is in right subtree
    5. This eliminates the need to check ancestors explicitly

    COMPLEXITY:
    ──────────
    Time: O(h) — Height of tree, O(log n) for balanced BST
    Space: O(1) — Iterative, no stack
    """
    current = root
    while current:
        if p.val < current.val and q.val < current.val:
            current = current.left
        elif p.val > current.val and q.val > current.val:
            current = current.right
        else:
            return current  # Split point → LCA found
    return None


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Lowest Common Ancestor (Binary Tree)
# ════════════════════════════════════════════════════════════════════════

def lowest_common_ancestor(root: Optional[TreeNode], p: TreeNode, q: TreeNode) -> Optional[TreeNode]:
    """
    QUESTION:
    ─────────
    Find LCA in a general binary tree (not necessarily BST).

    THOUGHT PROCESS:
    ────────────────
    1. Recursive DFS:
       - If current node is p or q, return it
       - Search left and right subtrees
       - If both sides return non-None → current is LCA
       - If only one side returns non-None → propagate that up
    2. This is a bottom-up approach — finds the deepest common ancestor

    COMPLEXITY:
    ──────────
    Time: O(n) — Worst case visit all nodes
    Space: O(h) — Recursion stack
    """
    if not root or root == p or root == q:
        return root

    left = lowest_common_ancestor(root.left, p, q)
    right = lowest_common_ancestor(root.right, p, q)

    if left and right:
        return root  # p and q are in different subtrees
    return left or right  # Both in one subtree


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Serialize and Deserialize Binary Tree
# ════════════════════════════════════════════════════════════════════════

def serialize(root: Optional[TreeNode]) -> str:
    """
    QUESTION:
    ─────────
    Design an algorithm to serialize a binary tree to a string and
    deserialize it back.

    THOUGHT PROCESS:
    ────────────────
    1. Use preorder traversal with a delimiter (',') and null marker ('#')
    2. Preorder naturally encodes tree structure
    3. Deserialize: Use queue to process nodes in order
    4. Alternative: Level order BFS with nulls

    COMPLEXITY:
    ──────────
    Time: O(n) — Visit each node
    Space: O(n) — String representation
    """

    def dfs(node: Optional[TreeNode]) -> None:
        if not node:
            result.append('#')
            return
        result.append(str(node.val))
        dfs(node.left)
        dfs(node.right)

    result = []
    dfs(root)
    return ','.join(result)


def deserialize(data: str) -> Optional[TreeNode]:
    """Deserialize a string back to a binary tree."""

    def dfs() -> Optional[TreeNode]:
        val = next(values)
        if val == '#':
            return None
        node = TreeNode(int(val))
        node.left = dfs()
        node.right = dfs()
        return node

    values = iter(data.split(','))
    return dfs()


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Binary Tree Right Side View
# ════════════════════════════════════════════════════════════════════════

def right_side_view(root: Optional[TreeNode]) -> List[int]:
    """
    QUESTION:
    ─────────
    Given a binary tree, imagine you're standing on the right side of it.
    Return the values of the nodes you can see (ordered top to bottom).

    Example:
        Input: 1 → (2 → 5, 3 → 4)
        Output: [1, 3, 4]

    THOUGHT PROCESS:
    ────────────────
    1. BFS level order: the last node at each level is the rightmost
    2. Or DFS: track level, first time visiting a level at a certain
       recursion order
    3. For right side view, process right before left in DFS
    4. This ensures the rightmost node of each level is seen first

    COMPLEXITY:
    ──────────
    Time: O(n) — Visit each node
    Space: O(h) — Recursion stack
    """
    result = []

    def dfs(node: Optional[TreeNode], level: int) -> None:
        if not node:
            return
        if level == len(result):
            result.append(node.val)  # First visit to this level
        dfs(node.right, level + 1)  # Process right first
        dfs(node.left, level + 1)

    dfs(root, 0)
    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: Kth Smallest Element in BST
# ════════════════════════════════════════════════════════════════════════

def kth_smallest(root: Optional[TreeNode], k: int) -> int:
    """
    QUESTION:
    ─────────
    Find the kth smallest element in a BST (1-indexed).

    Example:
        Input: root = 3 → (1 → None → 2, 4), k = 1
        Output: 1

    THOUGHT PROCESS:
    ────────────────
    1. Inorder traversal of BST gives sorted order
    2. Iterative inorder: stop after k elements
    3. This is O(h + k) because we stop early

    COMPLEXITY:
    ──────────
    Time: O(h + k) — h to reach smallest, k to find kth
    Space: O(h) — Stack
    """
    stack = []
    current = root

    while current or stack:
        while current:
            stack.append(current)
            current = current.left

        current = stack.pop()
        k -= 1
        if k == 0:
            return current.val

        current = current.right

    return -1  # k > tree size


# ════════════════════════════════════════════════════════════════════════
# QUESTION 10: Diameter of Binary Tree
# ════════════════════════════════════════════════════════════════════════

def diameter_of_binary_tree(root: Optional[TreeNode]) -> int:
    """
    QUESTION:
    ─────────
    Given a binary tree, find the length of the longest path between
    any two nodes (diameter). The path may or may not pass through root.

    Example:
        Input: 1 → (2 → 4 → 5, 3)
        Output: 3  (4 → 2 → 1 → 3, length = 3 edges)

    THOUGHT PROCESS:
    ────────────────
    1. For each node, diameter through that node = left_depth + right_depth
    2. We need max of (left_depth + right_depth) across all nodes
    3. Post-order traversal: compute depths bottom-up
    4. At each node: update global max with left+right, return 1+max(left,right)

    COMPLEXITY:
    ──────────
    Time: O(n) — Visit each node once
    Space: O(h) — Recursion stack
    """
    diameter = 0

    def depth(node: Optional[TreeNode]) -> int:
        nonlocal diameter
        if not node:
            return 0
        left = depth(node.left)
        right = depth(node.right)
        # Update diameter: path through this node
        diameter = max(diameter, left + right)
        # Return height of this subtree
        return 1 + max(left, right)

    depth(root)
    return diameter


# ════════════════════════════════════════════════════════════════════════
# HELPER: Build tree from list (level-order)
# ════════════════════════════════════════════════════════════════════════

def build_tree(values: List[Optional[int]]) -> Optional[TreeNode]:
    if not values:
        return None
    root = TreeNode(values[0])
    queue = deque([root])
    i = 1
    while queue and i < len(values):
        node = queue.popleft()
        if i < len(values) and values[i] is not None:
            node.left = TreeNode(values[i])
            queue.append(node.left)
        i += 1
        if i < len(values) and values[i] is not None:
            node.right = TreeNode(values[i])
            queue.append(node.right)
        i += 1
    return root


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("TREES — Interview Questions Demo")
    print("=" * 70)

    # Build sample tree: 3 → (9, 20 → (15, 7))
    tree = build_tree([3, 9, 20, None, None, 15, 7])

    # Q1
    print("\n1️⃣  Tree Traversals")
    print("-" * 40)
    print(f"   Inorder:   {inorder_traversal(tree)}")
    print(f"   Preorder:  {preorder_traversal(tree)}")
    print(f"   Postorder: {postorder_traversal(tree)}")

    # Q2
    print("\n2️⃣  Level Order Traversal")
    print("-" * 40)
    print(f"   Level Order: {level_order(tree)}")

    # Q3
    print("\n3️⃣  Validate BST")
    print("-" * 40)
    valid_bst = build_tree([2, 1, 3])
    invalid_bst = build_tree([5, 1, 4, None, None, 3, 6])
    print(f"   [2,1,3] is BST: {is_valid_bst(valid_bst)}")
    print(f"   [5,1,4,null,null,3,6] is BST: {is_valid_bst(invalid_bst)}")

    # Q4
    print("\n4️⃣  Maximum Depth")
    print("-" * 40)
    print(f"   Max depth: {max_depth(tree)}")

    # Q5
    print("\n5️⃣  LCA in BST")
    print("-" * 40)
    bst = build_tree([6, 2, 8, 0, 4, 7, 9, None, None, 3, 5])
    p = bst.left  # 2
    q = bst.right  # 8
    lca = lowest_common_ancestor_bst(bst, p, q)
    print(f"   BST: 6 → (2, 8)")
    print(f"   LCA of 2 and 8: {lca.val}")

    # Q6
    print("\n6️⃣  LCA in Binary Tree")
    print("-" * 40)
    lca_node = lowest_common_ancestor(tree, tree.left, tree.right)
    print(f"   LCA of 9 and 20: {lca_node.val}")

    # Q7
    print("\n7️⃣  Serialize/Deserialize")
    print("-" * 40)
    serialized = serialize(tree)
    deserialized = deserialize(serialized)
    print(f"   Serialized: {serialized}")
    print(f"   Deserialized inorder: {inorder_traversal(deserialized)}")

    # Q8
    print("\n8️⃣  Right Side View")
    print("-" * 40)
    print(f"   Right side view: {right_side_view(tree)}")

    # Q9
    print("\n9️⃣  Kth Smallest in BST")
    print("-" * 40)
    print(f"   1st smallest in [2,1,3]: {kth_smallest(valid_bst, 1)}")
    print(f"   2nd smallest in [2,1,3]: {kth_smallest(valid_bst, 2)}")

    # Q10
    print("\n🔟  Diameter of Binary Tree")
    print("-" * 40)
    dia_tree = build_tree([1, 2, 3, 4, 5])
    print(f"   Tree: [1, 2, 3, 4, 5]")
    print(f"   Diameter: {diameter_of_binary_tree(dia_tree)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
