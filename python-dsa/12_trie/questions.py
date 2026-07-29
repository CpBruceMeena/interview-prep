"""
TRIE (Prefix Tree) — Core Concepts & Interview Questions
==========================================================

Core Concepts:
──────────────
• Tree data structure for efficient string/prefix operations
• Each node represents a single character of the alphabet
• Root is empty, paths from root represent words/prefixes
• is_end flag marks the terminal character of a word
• Space: O(total characters across all strings)
• Time: O(k) for insert/search/prefix where k = string length

Why Trie over Hash Set:
───────────────────────
• Prefix search: Find all words with a given prefix — O(k) vs O(n) scan
• Lexicographic ordering: In-order traversal gives sorted strings
• Memory sharing: Common prefixes share storage space
• Auto-complete and spell-checking applications

Common Patterns:
────────────────
• Standard Trie (insert, search, startsWith)
• Word Search II (DFS + Trie pruning)
• Longest Common Prefix
• Prefix matching / auto-complete
• Replace Words / Filter sentences
• Design Add and Search Words with wildcards ('.')
"""

from typing import List, Optional, Dict


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Implement Trie (Prefix Tree)
# ════════════════════════════════════════════════════════════════════════

class TrieNode:
    """Node for a Trie. Each node has children dict and end marker."""
    def __init__(self):
        self.children: Dict[str, 'TrieNode'] = {}
        self.is_end = False


class Trie:
    """
    QUESTION:
    ─────────
    Implement a Trie with insert, search, and startsWith methods.

    Example:
        trie = Trie()
        trie.insert("apple")
        trie.search("apple") → True
        trie.search("app") → False
        trie.startsWith("app") → True
        trie.insert("app")
        trie.search("app") → True

    THOUGHT PROCESS:
    ────────────────
    1. Each node has: children (dict of char → TrieNode), is_end flag
    2. Insert: traverse each character, create nodes as needed,
       mark final node's is_end = True
    3. Search: traverse each character, if missing at any point → False
       return is_end of final node
    4. StartsWith: traverse each character, if missing → False, else True

    COMPLEXITY:
    ──────────
    insert: O(k) — k = length of word
    search: O(k)
    startsWith: O(p) — p = length of prefix
    Space: O(total characters inserted)
    """

    def __init__(self):
        self.root = TrieNode()

    def insert(self, word: str) -> None:
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end = True

    def search(self, word: str) -> bool:
        node = self._traverse(word)
        return node is not None and node.is_end

    def starts_with(self, prefix: str) -> bool:
        return self._traverse(prefix) is not None

    def _traverse(self, path: str) -> Optional[TrieNode]:
        """Follow path of characters, return last node or None."""
        node = self.root
        for char in path:
            if char not in node.children:
                return None
            node = node.children[char]
        return node


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Word Search II (Trie + DFS)
# ════════════════════════════════════════════════════════════════════════

def find_words(board: List[List[str]], words: List[str]) -> List[str]:
    """
    QUESTION:
    ─────────
    Given an m×n board of characters and a list of words, find all words
    on the board. Each word must be constructed from adjacent cells
    (horizontally or vertically). No cell may be used more than once
    per word.

    Example:
        Input: board = [["o","a","a","n"],
                        ["e","t","a","e"],
                        ["i","h","k","r"],
                        ["i","f","l","v"]],
               words = ["oath","pea","eat","rain"]
        Output: ["eat","oath"]

    THOUGHT PROCESS:
    ────────────────
    1. Brute force: Run Word Search for each word — O(n × m × 4^L × W)
    2. Build a Trie of all words, then DFS the board once
    3. During DFS, traverse the Trie in parallel with the board
    4. When we reach a node with is_end, that word is found
    5. Pruning: Remove word from Trie when found (set is_end = False)
       to avoid duplicates, and prune dead branches
    6. Optimization: Delete child nodes when all words through that
       path have been found (clean up Trie)

    COMPLEXITY:
    ──────────
    Time: O(m × n × 4^L) — One DFS exploring all word paths
    Space: O(total characters in words) — Trie storage
    """
    # Build Trie
    root = TrieNode()
    for word in words:
        node = root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end = True

    rows, cols = len(board), len(board[0])
    result = set()

    def dfs(r: int, c: int, node: TrieNode, path: List[str]) -> None:
        if node.is_end:
            result.add(''.join(path))
            node.is_end = False  # Avoid duplicates

        if r < 0 or r >= rows or c < 0 or c >= cols:
            return
        if board[r][c] == '#' or board[r][c] not in node.children:
            return

        char = board[r][c]
        child = node.children[char]

        # Mark visited
        board[r][c] = '#'
        path.append(char)

        # Explore 4 directions
        dfs(r + 1, c, child, path)
        dfs(r - 1, c, child, path)
        dfs(r, c + 1, child, path)
        dfs(r, c - 1, child, path)

        # Unmark (backtrack)
        board[r][c] = char
        path.pop()

        # Prune: If child has no children and is not end of another word,
        # delete it to keep Trie small
        if not child.children and not child.is_end:
            del node.children[char]

    for r in range(rows):
        for c in range(cols):
            dfs(r, c, root, [])

    return list(result)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Replace Words (Trie Prefix Match)
# ════════════════════════════════════════════════════════════════════════

def replace_words(dictionary: List[str], sentence: str) -> str:
    """
    QUESTION:
    ─────────
    Given a dictionary of roots and a sentence, replace each word with
    its shortest root prefix. If no root found, keep original word.

    Example:
        Input: dictionary = ["cat","bat","rat"], sentence = "the cattle was rattled by the battery"
        Output: "the cat was rat by the bat"

    THOUGHT PROCESS:
    ────────────────
    1. Build a Trie from all roots
    2. For each word in the sentence, traverse the Trie
    3. If we reach end of a root (is_end), replace entire word
    4. If we exit the Trie without finding a root, keep original word
    5. This is O(n × k) where n = words, k = avg word length

    COMPLEXITY:
    ──────────
    Time: O(total chars in dictionary + sentence)
    Space: O(total chars in dictionary)
    """
    # Build Trie from roots
    root = TrieNode()
    for word in dictionary:
        node = root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end = True

    def find_root(word: str) -> str:
        """Find the shortest root prefix of word."""
        node = root
        for i, char in enumerate(word):
            if char not in node.children:
                return word  # No root found
            node = node.children[char]
            if node.is_end:
                return word[:i + 1]  # Found root
        return word  # Full word matches prefix but not a root

    return ' '.join(find_root(w) for w in sentence.split())


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Design Add and Search Words (With Wildcard)
# ════════════════════════════════════════════════════════════════════════

class WordDictionary:
    """
    QUESTION:
    ─────────
    Design a data structure that supports adding words and searching
    with wildcards. '.' matches any single character.

    Example:
        wd = WordDictionary()
        wd.addWord("bad")
        wd.addWord("dad")
        wd.addWord("mad")
        wd.search("pad") → False
        wd.search("bad") → True
        wd.search(".ad") → True
        wd.search("b..") → True

    THOUGHT PROCESS:
    ────────────────
    1. Trie with DFS search that handles '.'
    2. When we encounter '.', try ALL children
    3. For non-wildcard characters, follow the Trie normally
    4. DFS + backtracking handles variable branching with '.'

    COMPLEXITY:
    ──────────
    addWord: O(k) — Insert into Trie
    search: O(26^k) worst for all dots, O(k) for no dots
    Space: O(total characters)
    """

    def __init__(self):
        self.root = TrieNode()

    def add_word(self, word: str) -> None:
        node = self.root
        for char in word:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
        node.is_end = True

    def search(self, word: str) -> bool:
        return self._dfs(self.root, word, 0)

    def _dfs(self, node: TrieNode, word: str, idx: int) -> bool:
        if idx == len(word):
            return node.is_end

        char = word[idx]
        if char == '.':
            # Try all possible children
            for child in node.children.values():
                if self._dfs(child, word, idx + 1):
                    return True
            return False
        else:
            # Follow exact character
            if char not in node.children:
                return False
            return self._dfs(node.children[char], word, idx + 1)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Longest Word in Dictionary
# ════════════════════════════════════════════════════════════════════════

def longest_word(words: List[str]) -> str:
    """
    QUESTION:
    ─────────
    Given an array of strings, find the longest word that can be built
    one character at a time by adding one letter from other words in
    the array. If tie, return lexicographically smallest.

    Example:
        Input: ["w","wo","wor","worl","world"]
        Output: "world"

    THOUGHT PROCESS:
    ────────────────
    1. Sort words by length and lexicographically
    2. Build a set of seen words
    3. For each word, check if prefix (word[:-1]) is in the set
    4. Track longest valid word
    5. Trie alternative: insert all words, DFS to find longest path
       where every node is an end of a word

    COMPLEXITY:
    ──────────
    Time: O(n log n + n × k) — Sorting + checks
    Space: O(n × k) — Set storage
    """
    words.sort()  # Sort lexicographically first
    words.sort(key=len)  # Then by length (stable sort preserves lex)

    seen = {''}
    longest = ''

    for word in words:
        if word[:-1] in seen:
            seen.add(word)
            if len(word) > len(longest):
                longest = word

    return longest


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Implement Trie for Auto-Complete System
# ════════════════════════════════════════════════════════════════════════

class AutoCompleteSystem:
    """
    QUESTION:
    ─────────
    Design a search autocomplete system. Given sentences and their
    frequencies, return the top 3 suggestions for each typed character.

    THOUGHT PROCESS:
    ────────────────
    1. Store sentences in a Trie where each node tracks sentences
       passing through it (with frequencies)
    2. As user types, traverse Trie to current node
    3. Return top 3 hot sentences from current node
    4. After space, save the completed sentence

    COMPLEXITY:
    ──────────
    Time: O(k + m log m) — k = typed chars, m = suggestions at node
    Space: O(total characters across all sentences)
    """

    def __init__(self, sentences: List[str], times: List[int]):
        self.root = TrieNode()
        self.current = self.root
        self.current_input = []

        # Insert sentences with frequencies
        for sentence, time in zip(sentences, times):
            self._add_sentence(sentence, time)

    def _add_sentence(self, sentence: str, count: int = 1) -> None:
        node = self.root
        for char in sentence:
            if char not in node.children:
                node.children[char] = TrieNode()
            node = node.children[char]
            # Track sentence frequency at each node
            if not hasattr(node, 'hot'):
                node.hot = {}
            node.hot[sentence] = node.hot.get(sentence, 0) + count
        node.is_end = True

    def input(self, c: str) -> List[str]:
        if c == '#':
            # Save completed sentence
            sentence = ''.join(self.current_input)
            self._add_sentence(sentence, 1)
            self.current = self.root
            self.current_input = []
            return []

        self.current_input.append(c)
        if c not in self.current.children:
            self.current = TrieNode()  # Dead node (no matches)
            return []

        self.current = self.current.children[c]
        # Get top 3 from current node
        if hasattr(self.current, 'hot'):
            suggestions = sorted(
                self.current.hot.items(),
                key=lambda x: (-x[1], x[0])  # By freq desc, then lexicographic
            )[:3]
            return [s[0] for s in suggestions]
        return []


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Concatenated Words
# ════════════════════════════════════════════════════════════════════════

def find_all_concatenated_words(words: List[str]) -> List[str]:
    """
    QUESTION:
    ─────────
    Given an array of strings, return all words that can be formed by
    concatenating two or more other words from the array.

    Example:
        Input: ["cat","cats","catsdogcats","dog","dogcatsdog","hippopotamuses","rat","ratcatdogcat"]
        Output: ["catsdogcats","dogcatsdog","ratcatdogcat"]

    THOUGHT PROCESS:
    ────────────────
    1. Sort words by length (shorter first)
    2. Use a set/prefix set to track words seen so far
    3. For each word, DFS/DP check if it can be formed by other words
    4. Only words shorter than current are candidates
    5. DFS with memoization for overlapping subproblems

    COMPLEXITY:
    ──────────
    Time: O(n × k²) — n words, k = avg length
    Space: O(n × k) — Word set
    """
    words.sort(key=len)
    word_set = set()
    result = []

    def can_form(word: str, memo: dict) -> bool:
        if word in memo:
            return memo[word]
        for i in range(1, len(word)):
            prefix = word[:i]
            suffix = word[i:]
            if prefix in word_set and (suffix in word_set or can_form(suffix, memo)):
                memo[word] = True
                return True
        memo[word] = False
        return False

    for word in words:
        if can_form(word, {}):
            result.append(word)
        word_set.add(word)

    return result


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("TRIE — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Implement Trie")
    print("-" * 40)
    trie = Trie()
    trie.insert("apple")
    print(f"   search('apple'): {trie.search('apple')}")
    print(f"   search('app'): {trie.search('app')}")
    print(f"   startsWith('app'): {trie.starts_with('app')}")
    trie.insert("app")
    print(f"   After insert('app'), search('app'): {trie.search('app')}")

    # Q2
    print("\n2️⃣  Word Search II")
    print("-" * 40)
    board = [
        ["o","a","a","n"],
        ["e","t","a","e"],
        ["i","h","k","r"],
        ["i","f","l","v"]
    ]
    words = ["oath","pea","eat","rain"]
    print(f"   Board: 4×4, Words: {words}")
    print(f"   Found: {sorted(find_words(board, words))}")

    # Q3
    print("\n3️⃣  Replace Words")
    print("-" * 40)
    dictionary = ["cat", "bat", "rat"]
    sentence = "the cattle was rattled by the battery"
    print(f"   Dictionary: {dictionary}")
    print(f"   Sentence: \"{sentence}\"")
    print(f"   Result: \"{replace_words(dictionary, sentence)}\"")

    # Q4
    print("\n4️⃣  Word Search with Wildcards")
    print("-" * 40)
    wd = WordDictionary()
    wd.add_word("bad")
    wd.add_word("dad")
    wd.add_word("mad")
    print(f"   Added: bad, dad, mad")
    print(f"   search('pad'): {wd.search('pad')}")
    print(f"   search('.ad'): {wd.search('.ad')}")
    print(f"   search('b..'): {wd.search('b..')}")

    # Q5
    print("\n5️⃣  Longest Word in Dictionary")
    print("-" * 40)
    words_list = ["w", "wo", "wor", "worl", "world"]
    print(f"   Words: {words_list}")
    print(f"   Longest: \"{longest_word(words_list)}\"")

    # Q6
    print("\n6️⃣  Auto-Complete System")
    print("-" * 40)
    ac = AutoCompleteSystem(
        ["i love you", "island", "ironman", "i love leetcode"],
        [5, 3, 2, 2]
    )
    print(f"   Input 'i': {ac.input('i')}")
    print(f"   Input ' ': {ac.input(' ')}")
    print(f"   Input '#': {ac.input('#')} (save)")

    # Q7
    print("\n7️⃣  Concatenated Words")
    print("-" * 40)
    words_list = ["cat","cats","catsdogcats","dog","dogcatsdog","hippopotamuses","rat","ratcatdogcat"]
    print(f"   Words: {words_list}")
    print(f"   Concatenated: {find_all_concatenated_words(words_list)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
