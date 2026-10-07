# Advanced Trees

> Python implementation — 4 questions covering core concepts and interview patterns.

ADVANCED TREES — Core Concepts & Interview Questions

---

```python
"""
ADVANCED TREES — Core Concepts & Interview Questions
=====================================================

Core Concepts:
──────────────
Self-balancing trees maintain O(log n) height for all operations:
• AVL Tree: Strictly height-balanced (|left_height - right_height| ≤ 1)
  - Rotations: LL, RR, LR, RL
  - Shorter than red-black → slightly faster lookups; more rotations on
    writes. Used when lookups dominate
• Red-Black Tree: Loosely balanced using color constraints
  - Root is black, no adjacent reds, equal black-height
  - Used in Java TreeMap/TreeSet (and HashMap's treeified buckets),
    C++ std::map in the common standard libraries, the Linux kernel
    (CFS scheduler run queue, epoll)
  - Insert: O(log n) with at most 2 rotations; delete at most 3

Multi-way Trees:
────────────────
• B-Tree: Generalization of BST with multiple keys per node
  - All leaves at same depth
  - Every node (except root) has between ceil(m/2)-1 and m-1 keys
  - Node size = one disk/SSD page, so each level costs one page read
• B+ Tree: B-Tree variant where only leaves store data
  - Internal nodes store keys only (routing table)
  - Leaves form a linked list for range queries
  - What databases actually mean by "B-tree index": MySQL InnoDB
    (clustered index), PostgreSQL nbtree (a Lehman-Yao B-link tree),
    SQLite tables; also filesystems such as Btrfs, XFS and NTFS
• Write-heavy alternative: LSM trees (RocksDB, Cassandra) trade read
  cost for sequential writes

Comparison:
───────────
| Feature | AVL | Red-Black | B-Tree | B+ Tree |
|---------|-----|-----------|--------|---------|
| Height | ≤ 1.44 log₂ n | ≤ 2 log₂(n+1) | O(log_t n) | O(log_t n) |
| Lookup | O(log n) | O(log n) | O(log n) | O(log n) |
| Insert | O(log n) | O(log n) | O(log n) | O(log n) |
| Delete | O(log n) | O(log n) | O(log n) | O(log n) |
| Cache Misses | High | High | Low | Lowest |
| Range (k results) | O(log n + k) | O(log n + k) | O(log n + k) | O(log n + k) |

All four answer a range query in O(log n + k) via an in-order walk.
The B+ tree's real advantage is I/O: after one descent, the k results
are read from consecutive leaf pages via sibling links, while the
B-tree's in-order walk keeps bouncing between internal and leaf pages.
(t = minimum degree / branching factor, typically hundreds per page.)
"""

from typing import List, Optional, Tuple, Union
from enum import Enum


# ════════════════════════════════════════════════════════════════════════
# AVL TREE — Self-Balancing BST with Height Balance
# ════════════════════════════════════════════════════════════════════════

class AVLNode:
    """Node for AVL Tree."""
    def __init__(self, key: int):
        self.key = key
        self.left: Optional['AVLNode'] = None
        self.right: Optional['AVLNode'] = None
        self.height = 1  # Leaf nodes have height 1


class AVLTree:
    """
    AVL Tree Implementation.

    Core Properties:
    ───────────────
    • For every node: |height(left) - height(right)| ≤ 1
    • Balance factor = height(left) - height(right)
    • On violation: perform rotations to restore balance

    Rotations:
    ──────────
    • LL (Right Rotate): Insert into left of left-heavy node
    • RR (Left Rotate): Insert into right of right-heavy node
    • LR (Left-Right): Insert into right of left-heavy → left rotate on child,
      then right rotate on parent
    • RL (Right-Left): Insert into left of right-heavy → right rotate on child,
      then left rotate on parent

    COMPLEXITY:
    ──────────
    Search: O(log n)
    Insert: O(log n) — with at most 1-2 rotations
    Delete: O(log n) — with O(log n) rotations (rebalancing up the tree)
    Space: O(n)
    """

    def __init__(self):
        self.root: Optional[AVLNode] = None

    def _height(self, node: Optional[AVLNode]) -> int:
        return node.height if node else 0

    def _balance_factor(self, node: Optional[AVLNode]) -> int:
        if not node:
            return 0
        return self._height(node.left) - self._height(node.right)

    def _update_height(self, node: AVLNode) -> None:
        node.height = 1 + max(self._height(node.left), self._height(node.right))

    def _rotate_right(self, y: AVLNode) -> AVLNode:
        r"""
        Right rotation (for LL imbalance):
            y               x
           / \             / \
          x   T3    →     T1  y
         / \                 / \
        T1  T2              T2  T3
        """
        x = y.left
        T2 = x.right

        x.right = y
        y.left = T2

        self._update_height(y)
        self._update_height(x)

        return x

    def _rotate_left(self, x: AVLNode) -> AVLNode:
        r"""
        Left rotation (for RR imbalance):
            x               y
           / \             / \
          T1  y     →     x   T3
             / \         / \
            T2  T3      T1  T2
        """
        y = x.right
        T2 = y.left

        y.left = x
        x.right = T2

        self._update_height(x)
        self._update_height(y)

        return y

    def insert(self, key: int) -> None:
        """Insert a key into the AVL tree."""
        self.root = self._insert(self.root, key)

    def _insert(self, node: Optional[AVLNode], key: int) -> AVLNode:
        # 1. Standard BST insert
        if not node:
            return AVLNode(key)

        if key < node.key:
            node.left = self._insert(node.left, key)
        elif key > node.key:
            node.right = self._insert(node.right, key)
        else:
            return node  # No duplicates

        # 2. Update height
        self._update_height(node)

        # 3. Get balance factor and rebalance
        balance = self._balance_factor(node)

        # Left-Left (LL) Case
        if balance > 1 and key < node.left.key:
            return self._rotate_right(node)

        # Right-Right (RR) Case
        if balance < -1 and key > node.right.key:
            return self._rotate_left(node)

        # Left-Right (LR) Case
        if balance > 1 and key > node.left.key:
            node.left = self._rotate_left(node.left)
            return self._rotate_right(node)

        # Right-Left (RL) Case
        if balance < -1 and key < node.right.key:
            node.right = self._rotate_right(node.right)
            return self._rotate_left(node)

        return node

    def delete(self, key: int) -> None:
        """Delete a key from the AVL tree."""
        self.root = self._delete(self.root, key)

    def _min_value_node(self, node: AVLNode) -> AVLNode:
        """Find the node with minimum key in the subtree."""
        current = node
        while current.left:
            current = current.left
        return current

    def _delete(self, node: Optional[AVLNode], key: int) -> Optional[AVLNode]:
        # 1. Standard BST delete
        if not node:
            return None

        if key < node.key:
            node.left = self._delete(node.left, key)
        elif key > node.key:
            node.right = self._delete(node.right, key)
        else:
            # Node with only one child or no child
            if not node.left:
                return node.right
            elif not node.right:
                return node.left

            # Node with two children: get inorder successor
            successor = self._min_value_node(node.right)
            node.key = successor.key
            node.right = self._delete(node.right, successor.key)

        if not node:
            return None

        # 2. Update height
        self._update_height(node)

        # 3. Rebalance
        balance = self._balance_factor(node)

        # Left-Left
        if balance > 1 and self._balance_factor(node.left) >= 0:
            return self._rotate_right(node)

        # Left-Right
        if balance > 1 and self._balance_factor(node.left) < 0:
            node.left = self._rotate_left(node.left)
            return self._rotate_right(node)

        # Right-Right
        if balance < -1 and self._balance_factor(node.right) <= 0:
            return self._rotate_left(node)

        # Right-Left
        if balance < -1 and self._balance_factor(node.right) > 0:
            node.right = self._rotate_right(node.right)
            return self._rotate_left(node)

        return node

    def search(self, key: int) -> bool:
        """Search for a key in the AVL tree."""
        current = self.root
        while current:
            if key == current.key:
                return True
            elif key < current.key:
                current = current.left
            else:
                current = current.right
        return False

    def inorder(self) -> List[int]:
        """Return inorder traversal (sorted order)."""
        result = []
        self._inorder(self.root, result)
        return result

    def _inorder(self, node: Optional[AVLNode], result: List[int]) -> None:
        if node:
            self._inorder(node.left, result)
            result.append(node.key)
            self._inorder(node.right, result)


# ════════════════════════════════════════════════════════════════════════
# RED-BLACK TREE (Conceptual Implementation)
# ════════════════════════════════════════════════════════════════════════

class Color(Enum):
    RED = 0
    BLACK = 1


class RBNode:
    """Node for Red-Black Tree."""
    def __init__(self, key: int):
        self.key = key
        self.color = Color.RED  # New nodes are always red
        self.left: Optional['RBNode'] = None
        self.right: Optional['RBNode'] = None
        self.parent: Optional['RBNode'] = None


class RedBlackTree:
    """
    Red-Black Tree Implementation.

    Properties:
    ──────────
    1. Every node is either red or black
    2. Root is always black
    3. Leaves (NIL) are black
    4. No two adjacent red nodes (red node's children are black)
    5. Every path from root to leaf has same number of black nodes

    THOUGHT PROCESS:
    ────────────────
    Insert fixes a potential violation of property 4 (red-red conflict).
    The fix depends on the uncle's color:
    • Uncle is RED → Recolor (no rotation needed)
    • Uncle is BLACK → Rotate + Recolor (same patterns as AVL)

    COMPLEXITY:
    ──────────
    Search: O(log n)
    Insert: O(log n) — at most 2 rotations
    Delete: O(log n) — at most 3 rotations
    Space: O(n)
    """

    def __init__(self):
        self.NIL = RBNode(0)
        self.NIL.color = Color.BLACK
        self.NIL.left = None
        self.NIL.right = None
        self.NIL.parent = None
        self.root = self.NIL

    def _rotate_left(self, x: RBNode) -> None:
        """Left rotate around node x."""
        y = x.right
        x.right = y.left
        if y.left != self.NIL:
            y.left.parent = x
        y.parent = x.parent
        if x.parent == self.NIL:
            self.root = y
        elif x == x.parent.left:
            x.parent.left = y
        else:
            x.parent.right = y
        y.left = x
        x.parent = y

    def _rotate_right(self, x: RBNode) -> None:
        """Right rotate around node x."""
        y = x.left
        x.left = y.right
        if y.right != self.NIL:
            y.right.parent = x
        y.parent = x.parent
        if x.parent == self.NIL:
            self.root = y
        elif x == x.parent.right:
            x.parent.right = y
        else:
            x.parent.left = y
        y.right = x
        x.parent = y

    def insert(self, key: int) -> None:
        """Insert a key into the Red-Black tree."""
        new_node = RBNode(key)
        new_node.left = self.NIL
        new_node.right = self.NIL

        # Standard BST insert
        y = self.NIL
        x = self.root

        while x != self.NIL:
            y = x
            if new_node.key < x.key:
                x = x.left
            else:
                x = x.right

        new_node.parent = y
        if y == self.NIL:
            self.root = new_node
        elif new_node.key < y.key:
            y.left = new_node
        else:
            y.right = new_node

        # Fix Red-Black properties
        self._insert_fixup(new_node)

    def _insert_fixup(self, z: RBNode) -> None:
        """Fix red-black tree after insertion."""
        while z.parent.color == Color.RED:
            if z.parent == z.parent.parent.left:
                y = z.parent.parent.right  # Uncle
                if y.color == Color.RED:
                    # Case 1: Uncle is red → recolor
                    z.parent.color = Color.BLACK
                    y.color = Color.BLACK
                    z.parent.parent.color = Color.RED
                    z = z.parent.parent
                else:
                    # Case 2/3: Uncle is black → rotate
                    if z == z.parent.right:
                        # Case 2: z is right child → left rotate
                        z = z.parent
                        self._rotate_left(z)
                    # Case 3: z is left child → right rotate + recolor
                    z.parent.color = Color.BLACK
                    z.parent.parent.color = Color.RED
                    self._rotate_right(z.parent.parent)
            else:
                # Symmetric case: parent is right child
                y = z.parent.parent.left  # Uncle
                if y.color == Color.RED:
                    z.parent.color = Color.BLACK
                    y.color = Color.BLACK
                    z.parent.parent.color = Color.RED
                    z = z.parent.parent
                else:
                    if z == z.parent.left:
                        z = z.parent
                        self._rotate_right(z)
                    z.parent.color = Color.BLACK
                    z.parent.parent.color = Color.RED
                    self._rotate_left(z.parent.parent)

        self.root.color = Color.BLACK

    def search(self, key: int) -> bool:
        """Search for a key in the Red-Black tree."""
        current = self.root
        while current != self.NIL:
            if key == current.key:
                return True
            elif key < current.key:
                current = current.left
            else:
                current = current.right
        return False

    def inorder(self) -> List[int]:
        """Return inorder traversal (sorted order)."""
        result = []
        self._inorder(self.root, result)
        return result

    def _inorder(self, node: RBNode, result: List[int]) -> None:
        if node != self.NIL:
            self._inorder(node.left, result)
            result.append(node.key)
            self._inorder(node.right, result)


# ════════════════════════════════════════════════════════════════════════
# B-TREE — Balanced Multi-way Search Tree
# ════════════════════════════════════════════════════════════════════════

class BTreeNode:
    """Node for B-Tree of order m (maximum children)."""
    def __init__(self, is_leaf: bool = True):
        self.keys: List[int] = []
        self.children: List['BTreeNode'] = []
        self.is_leaf = is_leaf


class BTree:
    """
    B-Tree of order m (minimum degree = t, max keys = 2t-1).

    Properties:
    ──────────
    • All leaves are at the same depth
    • Every node (except root) has at least t-1 keys
    • Every node (except root) has at most 2t-1 keys
    • Children count = keys count + 1 (for internal nodes)

    THOUGHT PROCESS:
    ────────────────
    • Insert: Find the leaf, insert in sorted position.
      If node is full (2t-1 keys), split before descending.
      Split: median key goes up, left and right halves become children.
    • Search: Linear scan within node, then recurse to appropriate child.
    • This "preemptive split" approach avoids needing to split on
      the way back up.

    COMPLEXITY:
    ──────────
    Search: O(log_t n) node visits (page reads); O(log n) comparisons
            in total with binary search inside each node
    Insert: O(t · log_t n) CPU — shifting keys within each split node —
            but still O(log_t n) page reads, which is what matters on disk
    Delete: O(log_t n) page reads (borrow from / merge with siblings)
    Space: O(n) — every non-root node is at least half full

    NOTE: this demo B-tree accepts duplicate keys and uses a linear scan
    inside nodes; real implementations binary-search each page.
    """

    def __init__(self, t: int = 3):
        self.root = BTreeNode(is_leaf=True)
        self.t = t  # Minimum degree

    def search(self, key: int) -> bool:
        """Search for a key in the B-Tree."""
        return self._search(self.root, key)

    def _search(self, node: BTreeNode, key: int) -> bool:
        i = 0
        while i < len(node.keys) and key > node.keys[i]:
            i += 1

        if i < len(node.keys) and key == node.keys[i]:
            return True

        if node.is_leaf:
            return False

        return self._search(node.children[i], key)

    def insert(self, key: int) -> None:
        """Insert a key into the B-Tree."""
        root = self.root
        # If root is full, grow the tree upward
        if len(root.keys) == 2 * self.t - 1:
            new_root = BTreeNode(is_leaf=False)
            new_root.children.append(self.root)
            self._split_child(new_root, 0)
            self.root = new_root

        self._insert_non_full(self.root, key)

    def _insert_non_full(self, node: BTreeNode, key: int) -> None:
        i = len(node.keys) - 1

        if node.is_leaf:
            # Insert key in sorted position
            node.keys.append(0)  # Extend the list
            while i >= 0 and key < node.keys[i]:
                node.keys[i + 1] = node.keys[i]
                i -= 1
            node.keys[i + 1] = key
        else:
            # Find the child to descend into
            while i >= 0 and key < node.keys[i]:
                i -= 1
            i += 1

            # If child is full, split it first
            if len(node.children[i].keys) == 2 * self.t - 1:
                self._split_child(node, i)
                # After split, decide which child to go to
                if key > node.keys[i]:
                    i += 1

            self._insert_non_full(node.children[i], key)

    def _split_child(self, parent: BTreeNode, i: int) -> None:
        """Split the i-th child of parent (which is full)."""
        t = self.t
        y = parent.children[i]  # Full child to split
        z = BTreeNode(is_leaf=y.is_leaf)

        # Save median key (at position t-1 in the full node)
        median_key = y.keys[t - 1]

        # z gets the largest t-1 keys (indices t to 2t-2)
        z.keys = y.keys[t:]

        # z gets the corresponding children (if not leaf)
        if not y.is_leaf:
            z.children = y.children[t:]

        # y keeps the smallest t-1 keys (indices 0 to t-2)
        y.keys = y.keys[:t - 1]
        if not y.is_leaf:
            y.children = y.children[:t]

        # Insert median key into parent at position i
        parent.keys.insert(i, median_key)
        # Add z as the next child in parent
        parent.children.insert(i + 1, z)

    def inorder(self) -> List[int]:
        """Return inorder traversal (sorted order)."""
        result = []
        self._inorder(self.root, result)
        return result

    def _inorder(self, node: BTreeNode, result: List[int]) -> None:
        if node:
            for i in range(len(node.keys)):
                if not node.is_leaf:
                    self._inorder(node.children[i], result)
                result.append(node.keys[i])
            if not node.is_leaf:
                self._inorder(node.children[len(node.keys)], result)


# ════════════════════════════════════════════════════════════════════════
# B+ TREE (Conceptual Explanation)
# ════════════════════════════════════════════════════════════════════════

"""
B+ TREE — Conceptual Overview
==============================

The B+ Tree is a B-Tree variant optimized for database indexing.
Only leaf nodes store data pointers; internal nodes act as routers.

Key Differences from B-Tree:
────────────────────────────
┌────────────────────┬─────────────────────┬──────────────────────┐
│ Feature           │ B-Tree             │ B+ Tree              │
├────────────────────┼─────────────────────┼──────────────────────┤
│ Data pointers     │ All nodes          │ Leaf nodes only      │
│ Internal nodes    │ Store keys + data  │ Store keys only      │
│ Leaf structure    │ Scattered          │ Linked list chain    │
│ Range queries     │ O(log n + k), but  │ O(log n + k), with   │
│                    │ random page reads  │ sequential leaf reads│
│ Cache efficiency  │ Lower              │ Higher (more keys    │
│                    │                     │ per internal node)   │
│ Fan-out          │ Lower              │ Higher               │
└────────────────────┴─────────────────────┴──────────────────────┘

Structure:
─────────
• Internal nodes: [k1, k2, ..., kn], each key is a routing value
  - Children: c0, c1, ..., cn where c_i holds keys in [k_i, k_{i+1})
    (c0 holds keys < k1)
• Leaf nodes: [k1:v1, k2:v2, ..., kn:vn] — key-value pairs
  - Leaves are linked: leaf.next = next_leaf (for range scans)
• All leaves are at the same depth

Operations:
───────────
• Search: Traverse from root, follow routing keys to leaf, scan leaf
• Insert: Find leaf, insert in sorted position. If leaf overflow:
  1. Split leaf: half keys stay, half go to new leaf
  2. Copy median key (first key of new leaf) up to parent
  3. If parent overflows, split and propagate up
• Delete: Find and remove. If leaf underflow:
  1. Try borrowing from sibling
  2. If can't borrow, merge with sibling
  3. Update parent key, propagate underflow

Why B+ Tree Wins for Databases:
───────────────────────────────
1. Higher fan-out = shorter tree = fewer disk seeks
   - B+ Tree with order 100: 100^4 = 100M records in 4 levels; real
     fan-out with 8-16 KB pages is often several hundred, so 3-4
     levels cover billions of rows
2. Range queries: just walk the leaf linked list
   - B-Tree's in-order walk climbs back into internal nodes (more,
     non-sequential page reads)
3. Better cache locality: the few internal levels stay in the buffer
   pool, so a lookup usually costs ~1 physical read (the leaf)
4. Internal nodes store only keys (more keys per node)

What interviewers probe next:
• Clustered vs secondary index (InnoDB secondary leaves store the
  primary key → a second lookup unless the index is covering)
• Why random UUID primary keys hurt: inserts land on random leaves →
  page splits and poor cache locality; time-ordered IDs (UUIDv7) fix it
• Concurrency: latch crabbing / B-link trees (PostgreSQL) so readers
  don't block on splits
"""


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("ADVANCED TREES — Interview Questions Demo")
    print("=" * 70)

    # AVL Tree
    print("\n🌳 AVL TREE")
    print("-" * 40)
    avl = AVLTree()
    keys = [10, 20, 30, 40, 50, 25]
    for k in keys:
        avl.insert(k)
        print(f"   Insert {k}: inorder = {avl.inorder()}")
    print(f"   Search 25: {avl.search(25)}")
    print(f"   Search 100: {avl.search(100)}")
    avl.delete(40)
    print(f"   After delete 40: {avl.inorder()}")
    avl.delete(50)
    print(f"   After delete 50: {avl.inorder()}")
    print(f"   Height: {avl._height(avl.root)}")

    # Red-Black Tree
    print("\n🔴⚫ RED-BLACK TREE")
    print("-" * 40)
    rbt = RedBlackTree()
    for k in [10, 20, 30, 15, 25, 5, 1]:
        rbt.insert(k)
    print(f"   Insert [10,20,30,15,25,5,1]: {rbt.inorder()}")
    print(f"   Search 15: {rbt.search(15)}")
    print(f"   Search 100: {rbt.search(100)}")

    # B-Tree
    print("\n🌲 B-TREE (min degree t=3)")
    print("-" * 40)
    bt = BTree(t=3)
    for k in [10, 20, 5, 6, 12, 30, 7, 17]:
        bt.insert(k)
    print(f"   Inserted [10,20,5,6,12,30,7,17]")
    inorder = bt.inorder()
    print(f"   Inorder: {inorder}")
    print(f"   Sorted? {inorder == sorted(inorder)}")
    print(f"   Search 17: {bt.search(17)}")
    print(f"   Search 99: {bt.search(99)}")

    # B+ Tree Concept
    print("\n🗄️  B+ TREE (Conceptual)")
    print("-" * 40)
    print("   See docstring for detailed explanation")
    print("   Key advantage: Range queries via leaf linked list")
    print("   Used in: MySQL InnoDB, PostgreSQL (nbtree), SQLite, many filesystems")
    print("   Fan-out of 100: 100^4 = 100M records in 4 levels")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()

```

---

[← Back to DSA Overview](../index.md)
