# Strings

> Python implementation — 10 questions covering core concepts and interview patterns.

STRINGS — Core Concepts & Interview Questions

---

```python
"""
STRINGS — Core Concepts & Interview Questions
==============================================

Core Concepts:
──────────────
• Strings are immutable in Python — each operation creates a new string
• Character encoding: ASCII (128), Extended ASCII (256), Unicode
• String slicing: s[i:j:k] — create new string, O(k) time
• Common operations: join(), split(), strip(), find(), count()
• Regular expressions for pattern matching (re module)
• String builders: Use list of chars + join() for efficiency

Common Patterns:
────────────────
• Two pointers (starting from both ends)
• Sliding window (longest substring without repeating)
• Palindrome expansion (center-out approach)
• Hashing / frequency counting (anagrams, character maps)
• KMP Algorithm (pattern matching)
• Trie (prefix matching, autocomplete)
• Rolling hash (Rabin-Karp for substring search)
"""

from typing import List, Optional, Tuple
from collections import Counter, defaultdict


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Longest Substring Without Repeating Characters
# ════════════════════════════════════════════════════════════════════════

def length_of_longest_substring(s: str) -> int:
    """
    QUESTION:
    ─────────
    Given a string s, find the length of the longest substring without
    repeating characters.

    Example:
        Input: "abcabcbb"
        Output: 3  ("abc")

    THOUGHT PROCESS:
    ────────────────
    1. Brute Force: Check all O(n²) substrings — O(n³) total
    2. Sliding Window with Hash Map:
       - Maintain window [left, right] with unique characters
       - When a duplicate is found, shrink from the left
       - Track last seen index of each character
       - Window is valid when no characters repeat
    3. Key insight: When we see a duplicate char, we jump left pointer
       to max(left, last_seen[char] + 1)
       This avoids checking each position one by one

    COMPLEXITY:
    ──────────
    Time: O(n) — Each character visited at most twice
    Space: O(min(m, n)) — Hash map of unique chars (m = charset size)
    """
    char_index = {}  # character -> last seen index
    max_length = 0
    left = 0

    for right, char in enumerate(s):
        # If char seen before and within current window
        if char in char_index and char_index[char] >= left:
            # Move left to just after the previous occurrence
            left = char_index[char] + 1

        # Update last seen index
        char_index[char] = right
        # Update max length
        max_length = max(max_length, right - left + 1)

    return max_length


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Longest Palindromic Substring
# ════════════════════════════════════════════════════════════════════════

def longest_palindrome(s: str) -> str:
    """
    QUESTION:
    ─────────
    Given a string s, return the longest palindromic substring.

    Example:
        Input: "babad"
        Output: "bab" or "aba"

    THOUGHT PROCESS:
    ────────────────
    1. Brute Force: Check all O(n²) substrings for palindrome — O(n³)
    2. Center Expansion:
       - A palindrome mirrors around its center
       - Each character (and gap between chars) can be a center
       - Expand outward from center while palindrome condition holds
    3. Two types of centers:
       - Odd length: center is a character — s[i]
       - Even length: center is between chars — s[i] and s[i+1]
    4. Total centers = 2n - 1 (n single + n-1 gaps)

    COMPLEXITY:
    ──────────
    Time: O(n²) — n centers, each expanding up to n times
    Space: O(1) — Only constant extra space (excluding output)
    """
    if not s:
        return ""

    def expand(left: int, right: int) -> str:
        """Expand outward from center while palindrome holds."""
        while left >= 0 and right < len(s) and s[left] == s[right]:
            left -= 1
            right += 1
        return s[left + 1:right]

    longest = ""

    for i in range(len(s)):
        # Odd length palindrome
        odd_pal = expand(i, i)
        if len(odd_pal) > len(longest):
            longest = odd_pal

        # Even length palindrome
        even_pal = expand(i, i + 1)
        if len(even_pal) > len(longest):
            longest = even_pal

    return longest


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: String to Integer (atoi)
# ════════════════════════════════════════════════════════════════════════

def my_atoi(s: str) -> int:
    """
    QUESTION:
    ─────────
    Implement atoi which converts a string to a 32-bit signed integer.
    Discard leading whitespace, then optional +/- sign, then digits.
    Clamp to [−2³¹, 2³¹−1].

    Example:
        Input: "   -42"
        Output: -42

    THOUGHT PROCESS:
    ────────────────
    1. Three phases: skip whitespace → parse sign → convert digits
    2. Handle edge cases at each phase:
       - Empty string → return 0
       - Only whitespace → return 0
       - +/- after whitespace but before digits
       - Overflow → clamp to 32-bit integer range
    3. Overflow detection: Before multiplying by 10, check if
       result > (MAX_INT - digit) / 10

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass through relevant characters
    Space: O(1) — No extra space
    """
    if not s:
        return 0

    i, n = 0, len(s)
    INT_MAX, INT_MIN = 2**31 - 1, -2**31

    # Phase 1: Skip leading whitespace
    while i < n and s[i] == ' ':
        i += 1

    if i >= n:
        return 0

    # Phase 2: Parse sign
    sign = 1
    if s[i] == '+' or s[i] == '-':
        sign = -1 if s[i] == '-' else 1
        i += 1

    # Phase 3: Convert digits
    result = 0
    while i < n and s[i].isdigit():
        digit = int(s[i])

        # Overflow check before multiplication
        if result > (INT_MAX - digit) // 10:
            return INT_MAX if sign == 1 else INT_MIN

        result = result * 10 + digit
        i += 1

    return sign * result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Valid Anagram
# ════════════════════════════════════════════════════════════════════════

def is_anagram(s: str, t: str) -> bool:
    """
    QUESTION:
    ─────────
    Given two strings s and t, return true if t is an anagram of s.

    Example:
        Input: s = "anagram", t = "nagaram"
        Output: true

    THOUGHT PROCESS:
    ────────────────
    1. Sort both strings and compare — O(n log n), O(n)
    2. Frequency counter:
       - Count characters in s, decrement for t
       - If all counts are zero, it's an anagram
    3. Optimization: Early exit if lengths differ
    4. Alternative: Use array[26] for lowercase letters only

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass through each string
    Space: O(1) — At most 26 or 128 entries (constant charset)
    """
    if len(s) != len(t):
        return False

    # Use array for lowercase letters (or dict for general)
    counts = [0] * 26

    for char in s:
        counts[ord(char) - ord('a')] += 1

    for char in t:
        idx = ord(char) - ord('a')
        counts[idx] -= 1
        if counts[idx] < 0:
            return False

    return True


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Group Anagrams
# ════════════════════════════════════════════════════════════════════════

def group_anagrams(strs: List[str]) -> List[List[str]]:
    """
    QUESTION:
    ─────────
    Given an array of strings, group the anagrams together.

    Example:
        Input: ["eat", "tea", "tan", "ate", "nat", "bat"]
        Output: [["eat","tea","ate"], ["tan","nat"], ["bat"]]

    THOUGHT PROCESS:
    ────────────────
    1. Two anagram detection strategies:
       a) Sorted string as key: "eat" → "aet", "tea" → "aet"
       b) Character count tuple as key: "eat" → (1,0,0,0,1,...)
    2. Approach a is simpler, approach b is faster for long strings
    3. Use hash map: key = normalized form, value = list of strings
    4. Time complexity: O(n * k log k) for sort-based
       or O(n * k) for count-based (k = max string length)

    COMPLEXITY:
    ──────────
    Time: O(n * k log k) — n strings, sorting each of length k
    Space: O(n * k) — Storing all strings in hash map
    """
    groups = defaultdict(list)

    for s in strs:
        # Use sorted string as canonical form
        key = ''.join(sorted(s))
        groups[key].append(s)

    return list(groups.values())


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Longest Palindromic Substring — Manacher's Algorithm
# ════════════════════════════════════════════════════════════════════════

def longest_palindrome_manacher(s: str) -> str:
    """
    QUESTION:
    ─────────
    Find longest palindromic substring in O(n).

    THOUGHT PROCESS:
    ────────────────
    1. Standard center expansion is O(n²)
    2. Manacher's uses previously computed palindromes to skip expansions
    3. Transform string by inserting '|' between chars (handles even length)
       "abc" → "|a|b|c|"
    4. Maintain center and right boundary of current rightmost palindrome
    5. For each position, use mirror position for initial radius guess

    COMPLEXITY:
    ──────────
    Time: O(n) — Linear, each position examined at most twice
    Space: O(n) — Transformed string and radius array
    """
    if not s:
        return ""

    # Transform: "abc" → "|a|b|c|"
    transformed = '|' + '|'.join(s) + '|'
    n = len(transformed)
    radii = [0] * n

    center = 0  # Center of current rightmost palindrome
    right = 0   # Right boundary of current rightmost palindrome

    for i in range(n):
        # If i is within previous palindrome, use mirror
        if i < right:
            mirror = 2 * center - i  # Mirror of i around center
            radii[i] = min(right - i, radii[mirror])

        # Expand outward
        while (i - radii[i] - 1 >= 0 and
               i + radii[i] + 1 < n and
               transformed[i - radii[i] - 1] == transformed[i + radii[i] + 1]):
            radii[i] += 1

        # Update center and right if we expanded past right
        if i + radii[i] > right:
            center = i
            right = i + radii[i]

    # Find max radius and center
    max_radius = max(radii)
    center_idx = radii.index(max_radius)

    # Convert back to original string
    start = (center_idx - max_radius) // 2
    return s[start:start + max_radius]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Count Palindromic Substrings
# ════════════════════════════════════════════════════════════════════════

def count_substrings(s: str) -> int:
    """
    QUESTION:
    ─────────
    Given a string, return the number of palindromic substrings.

    Example:
        Input: "abc"
        Output: 3  ("a", "b", "c")

        Input: "aaa"
        Output: 6  ("a","a","a","aa","aa","aaa")

    THOUGHT PROCESS:
    ────────────────
    1. Center expansion approach (same as longest palindrome)
    2. Each center expands and counts each palindrome found
    3. Count when expanding: each expansion that works = 1 palindrome
    4. Total centers: 2n - 1 (n odd + n-1 even)

    COMPLEXITY:
    ──────────
    Time: O(n²) — n centers expanding up to n times
    Space: O(1) — Constant extra space
    """
    if not s:
        return 0

    n = len(s)
    total = 0

    def expand_count(left: int, right: int) -> int:
        count = 0
        while left >= 0 and right < n and s[left] == s[right]:
            count += 1
            left -= 1
            right += 1
        return count

    for i in range(n):
        total += expand_count(i, i)      # Odd length
        total += expand_count(i, i + 1)  # Even length

    return total


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Minimum Window Substring
# ════════════════════════════════════════════════════════════════════════

def min_window(s: str, t: str) -> str:
    """
    QUESTION:
    ─────────
    Given two strings s and t, return the minimum window substring of s
    such that every character in t (including duplicates) is included.

    Example:
        Input: s = "ADOBECODEBANC", t = "ABC"
        Output: "BANC"

    THOUGHT PROCESS:
    ────────────────
    1. Sliding window with two frequency maps
    2. Keep track of "required" vs "formed" character counts
    3. Expand right to include characters, shrink left when window is valid
    4. Window is valid when formed == required
    5. Track minimum length and its start index

    COMPLEXITY:
    ──────────
    Time: O(m + n) — Each character visited twice (expand + contract)
    Space: O(k) — k = unique characters in t
    """
    if not s or not t:
        return ""

    target_counts = Counter(t)
    required = len(target_counts)
    formed = 0
    window_counts = defaultdict(int)

    left = 0
    min_len = float('inf')
    min_start = 0

    for right, char in enumerate(s):
        # Expand window
        window_counts[char] += 1

        if char in target_counts and window_counts[char] == target_counts[char]:
            formed += 1

        # Contract window while it's valid
        while left <= right and formed == required:
            # Update minimum
            window_len = right - left + 1
            if window_len < min_len:
                min_len = window_len
                min_start = left

            # Shrink from left
            left_char = s[left]
            window_counts[left_char] -= 1
            if left_char in target_counts and window_counts[left_char] < target_counts[left_char]:
                formed -= 1

            left += 1

    return s[min_start:min_start + min_len] if min_len != float('inf') else ""


# ════════════════════════════════════════════════════════════════════════
# QUESTION 9: Encode and Decode Strings
# ════════════════════════════════════════════════════════════════════════

def encode(strs: List[str]) -> str:
    """
    QUESTION:
    ─────────
    Design an algorithm to encode a list of strings into a single string
    and decode it back. The encoded string should be self-delimiting.

    Example:
        Input: ["hello", "world", ""]
        After encode, then decode → ["hello", "world", ""]

    THOUGHT PROCESS:
    ────────────────
    1. Simple approach: Use length prefix with delimiter
       "5#hello5#world0#"
    2. Why length prefix? If we just use a delimiter like "#" or ",",
       the strings might contain that character
    3. Length prefix ensures we know exactly how many chars to read
    4. Chars after length can be anything — safe from delimiter collision

    COMPLEXITY:
    ──────────
    Time: O(n) — Linear in total characters
    Space: O(n) — Result string
    """

    # Encode: "hello" → "5#hello"
    encoded_parts = [f"{len(s)}#{s}" for s in strs]
    return ''.join(encoded_parts)


def decode(s: str) -> List[str]:
    """Decode a single string back to a list of strings."""
    result = []
    i = 0

    while i < len(s):
        # Find the delimiter
        j = s.find('#', i)
        if j == -1:
            break

        # Extract length
        length = int(s[i:j])
        # Extract string of that length
        start = j + 1
        end = start + length
        result.append(s[start:end])
        i = end

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 10: Repeated DNA Sequences
# ════════════════════════════════════════════════════════════════════════

def find_repeated_dna_sequences(s: str) -> List[str]:
    """
    QUESTION:
    ─────────
    Given a string representing a DNA sequence (A, C, G, T), find all
    10-letter-long subsequences that occur more than once.

    Example:
        Input: "AAAAACCCCCAAAAACCCCCCAAAAAGGGTTT"
        Output: ["AAAAACCCCC", "CCCCCAAAAA"]

    THOUGHT PROCESS:
    ────────────────
    1. Brute Force: Store all substrings in set — O(n·10) time, O(n) space
    2. Rolling Hash (Rabin-Karp):
       - Map each nucleotide to a 2-bit value: A=00, C=01, G=10, T=11
       - Each 10-letter sequence → 20-bit integer
       - Rolling hash: drop leftmost, add rightmost using bit operations
       - O(n) time, no string slicing overhead
    3. This is a classic use case for rolling hash optimization

    COMPLEXITY:
    ──────────
    Time: O(n) — Linear scan with constant-time rolling hash
    Space: O(n) — Store seen sequences
    """
    if len(s) <= 10:
        return []

    # Map nucleotide to 2-bit value
    mapping = {'A': 0, 'C': 1, 'G': 2, 'T': 3}
    seen = set()
    repeated = set()

    # Compute hash of first 10 characters
    hash_val = 0
    for i in range(10):
        hash_val = (hash_val << 2) | mapping[s[i]]

    seen.add(hash_val)

    # Slide the window
    mask = (1 << 20) - 1  # 20 bits mask (10 chars * 2 bits)

    for i in range(10, len(s)):
        # Remove leftmost, add rightmost
        hash_val = ((hash_val << 2) | mapping[s[i]]) & mask

        if hash_val in seen:
            repeated.add(s[i - 9:i + 1])
        else:
            seen.add(hash_val)

    return list(repeated)


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("STRINGS — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Longest Substring Without Repeating Characters")
    print("-" * 40)
    s = "abcabcbb"
    print(f"   Input: \"{s}\"")
    print(f"   Length: {length_of_longest_substring(s)}")

    # Q2
    print("\n2️⃣  Longest Palindromic Substring")
    print("-" * 40)
    s = "babad"
    print(f"   Input: \"{s}\"")
    print(f"   Longest Pal: \"{longest_palindrome(s)}\"")
    print(f"   Manacher:   \"{longest_palindrome_manacher(s)}\"")

    # Q3
    print("\n3️⃣  String to Integer (atoi)")
    print("-" * 40)
    test_cases = ["42", "   -42", "4193 with words", "words and 987"]
    for tc in test_cases:
        print(f"   \"{tc}\" → {my_atoi(tc)}")

    # Q4
    print("\n4️⃣  Valid Anagram")
    print("-" * 40)
    pairs = [("anagram", "nagaram"), ("rat", "car")]
    for s, t in pairs:
        print(f"   \"{s}\" vs \"{t}\": {is_anagram(s, t)}")

    # Q5
    print("\n5️⃣  Group Anagrams")
    print("-" * 40)
    strs = ["eat", "tea", "tan", "ate", "nat", "bat"]
    print(f"   Input: {strs}")
    print(f"   Groups: {group_anagrams(strs)}")

    # Q7
    print("\n7️⃣  Count Palindromic Substrings")
    print("-" * 40)
    test_strings = ["abc", "aaa"]
    for ts in test_strings:
        print(f"   \"{ts}\": {count_substrings(ts)}")

    # Q8
    print("\n8️⃣  Minimum Window Substring")
    print("-" * 40)
    s, t = "ADOBECODEBANC", "ABC"
    print(f"   s=\"{s}\", t=\"{t}\"")
    print(f"   Min Window: \"{min_window(s, t)}\"")

    # Q9
    print("\n9️⃣  Encode / Decode Strings")
    print("-" * 40)
    strs = ["hello", "world", ""]
    encoded = encode(strs)
    decoded = decode(encoded)
    print(f"   Original: {strs}")
    print(f"   Encoded: \"{encoded}\"")
    print(f"   Decoded: {decoded}")

    # Q10
    print("\n🔟  Repeated DNA Sequences")
    print("-" * 40)
    dna = "AAAAACCCCCAAAAACCCCCCAAAAAGGGTTT"
    print(f"   Input: {dna}")
    print(f"   Repeated: {find_repeated_dna_sequences(dna)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()

```

---

[← Back to DSA Overview](../index.md)
