"""
ADVANCED STRING ALGORITHMS — Core Concepts & Interview Questions
=================================================================

Core Concepts:
──────────────
String matching algorithms for pattern searching in text:
• Naive: O(m × n) — check every position
• KMP (Knuth-Morris-Pratt): O(n + m) — uses LPS array to avoid backtracking
• Rabin-Karp: O(n + m) average — uses rolling hash for pattern matching
• Z-Algorithm: O(n) — computes Z-array for pattern matching
• Boyer-Moore: O(n/m) best, O(nm) worst — skip heuristic

String Transformation / Processing:
───────────────────────────────────
• Manacher's Algorithm: O(n) — find all palindromic substrings
• Run-Length Encoding (RLE): compress consecutive repeated chars
• Burrows-Wheeler Transform (BWT): reversible transform for compression
• Levenshtein Distance: edit distance between strings (covered in DP)
• Longest Common Substring: DP + suffix array approaches

Suffix Data Structures:
───────────────────────
• Suffix Array: sorted suffixes — O(n log n) to build
• LCP Array: longest common prefix between adjacent suffixes
• Suffix Tree: compressed trie of all suffixes — O(n) suffix links
"""

from typing import List, Tuple, Optional


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: KMP (Knuth-Morris-Pratt) Pattern Matching
# ════════════════════════════════════════════════════════════════════════

def kmp_search(text: str, pattern: str) -> List[int]:
    """
    QUESTION:
    ─────────
    Implement KMP pattern matching algorithm. Return all starting indices
    where pattern occurs in text.

    Example:
        Input: text = "ABABDABACDABABCABAB", pattern = "ABABCABAB"
        Output: [10]

    THOUGHT PROCESS:
    ────────────────
    1. Naive matching backtracks on mismatch — O(m × n)
    2. KMP preprocessing: Build LPS (Longest Proper Prefix which is also Suffix)
       - LPS[i] = length of longest proper prefix of pattern[0:i] that is
         also a suffix of pattern[0:i]
       - This tells us how much to skip on mismatch
    3. During search:
       - When characters match: advance both pointers
       - On mismatch: if j > 0, set j = LPS[j-1]; else advance i
       - When j == len(pattern): found match, set j = LPS[j-1] to continue
    4. Key insight: KMP never backtracks the text pointer i

    COMPLEXITY:
    ──────────
    Time: O(n + m) — LPS construction O(m) + search O(n)
    Space: O(m) — LPS array of size m
    """
    if not pattern:
        return [] if not text else [0]

    # Build LPS (Longest Prefix Suffix) array
    lps = [0] * len(pattern)
    length = 0  # Length of previous longest prefix suffix
    i = 1

    while i < len(pattern):
        if pattern[i] == pattern[length]:
            length += 1
            lps[i] = length
            i += 1
        else:
            if length != 0:
                length = lps[length - 1]
            else:
                lps[i] = 0
                i += 1

    # Search using LPS
    result = []
    i = j = 0  # i = text index, j = pattern index

    while i < len(text):
        if text[i] == pattern[j]:
            i += 1
            j += 1

        if j == len(pattern):
            result.append(i - j)
            j = lps[j - 1]
        elif i < len(text) and text[i] != pattern[j]:
            if j != 0:
                j = lps[j - 1]
            else:
                i += 1

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Rabin-Karp (Rolling Hash Pattern Matching)
# ════════════════════════════════════════════════════════════════════════

def rabin_karp(text: str, pattern: str) -> List[int]:
    """
    QUESTION:
    ─────────
    Implement Rabin-Karp string matching using rolling hash.
    Return all starting indices where pattern occurs in text.

    Example:
        Input: text = "CCACCACCED", pattern = "ACC"
        Output: [2, 5]

    THOUGHT PROCESS:
    ────────────────
    1. Compute hash of pattern and first window of text
    2. Slide the window: update hash in O(1) using rolling hash formula
    3. If hashes match, verify character-by-character (spurious hit)
    4. Rolling hash formula (base = 256, mod = 101):
       - hash = (hash - text[i] * base^(m-1)) * base + text[i+m]
       - All modulo prime to avoid overflow
    5. Good for multi-pattern search and plagiarism detection

    COMPLEXITY:
    ──────────
    Time: O(n + m) average, O(nm) worst (many spurious hits)
    Space: O(1) — only constant variables
    """
    if not pattern or len(pattern) > len(text):
        return []

    base = 256  # Number of characters in alphabet
    prime = 101  # A prime number for modulo

    m, n = len(pattern), len(text)
    pattern_hash = 0
    window_hash = 0
    h = 1  # base^(m-1) mod prime

    # Compute base^(m-1) % prime
    for _ in range(m - 1):
        h = (h * base) % prime

    # Compute hash of pattern and first window
    for i in range(m):
        pattern_hash = (base * pattern_hash + ord(pattern[i])) % prime
        window_hash = (base * window_hash + ord(text[i])) % prime

    result = []

    for i in range(n - m + 1):
        # If hashes match, verify characters
        if pattern_hash == window_hash:
            if text[i:i + m] == pattern:
                result.append(i)

        # Compute hash for next window
        if i < n - m:
            window_hash = (base * (window_hash - ord(text[i]) * h) +
                           ord(text[i + m])) % prime

            # Handle negative hash
            if window_hash < 0:
                window_hash += prime

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Z-Algorithm (Linear Time Pattern Matching)
# ════════════════════════════════════════════════════════════════════════

def z_algorithm(text: str) -> List[int]:
    """
    Z-Algorithm: Compute Z-array for a string.
    Z[i] = longest substring starting at i that matches the prefix.

    Example:
        Input: "aaabaaab"
        Output: [8, 3, 2, 1, 0, 2, 1, 0]

    THOUGHT PROCESS:
    ────────────────
    1. Z-box concept: maintain [L, R] interval that matches prefix,
       with R being the rightmost such boundary.
    2. For each position i:
       - If i > R: compute Z[i] by comparing naively
       - If i ≤ R: Z[i] = min(Z[i-L], R-i+1), then expand
    3. This is the foundation of many string algorithms

    COMPLEXITY:
    ──────────
    Time: O(n) — Each character compared at most twice
    Space: O(n) — Z-array
    """
    n = len(text)
    z = [0] * n
    z[0] = n  # The whole string matches prefix at position 0

    left = right = 0

    for i in range(1, n):
        # If i is within Z-box, use previously computed values
        if i <= right:
            z[i] = min(right - i + 1, z[i - left])

        # Expand Z-box
        while i + z[i] < n and text[z[i]] == text[i + z[i]]:
            z[i] += 1

        # Update Z-box if we expanded past R
        if i + z[i] - 1 > right:
            left = i
            right = i + z[i] - 1

    return z


def z_search(text: str, pattern: str) -> List[int]:
    """
    Pattern matching using Z-Algorithm.
    Concatenate pattern + '$' + text, compute Z-array.

    Example:
        Input: text = "ABABDABACDABABCABAB", pattern = "ABABCABAB"
        Output: [10]

    THOUGHT PROCESS:
    ────────────────
    1. Create combined string: pattern + '$' + text
       ('$' is a sentinel character not in pattern or text)
    2. Compute Z-array of combined string
    3. Every position i where Z[i] == len(pattern) indicates a match

    COMPLEXITY:
    ──────────
    Time: O(n + m) — Linear
    Space: O(n + m) — Z-array
    """
    combined = pattern + '$' + text
    z = z_algorithm(combined)
    pattern_len = len(pattern)

    result = []
    for i in range(pattern_len + 1, len(combined)):
        if z[i] == pattern_len:
            result.append(i - pattern_len - 1)

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Manacher's Algorithm (All Palindromic Substrings)
# ════════════════════════════════════════════════════════════════════════

def manacher(s: str) -> Tuple[int, int]:
    """
    QUESTION:
    ─────────
    Find the longest palindromic substring using Manacher's O(n) algorithm.

    Example:
        Input: "babad"
        Output: (0, 2)  -> "bab" (start, end inclusive)

    THOUGHT PROCESS:
    ────────────────
    1. Transform string: insert '|' between chars to handle even length
       "abc" → "|a|b|c|" — now all palindromes have odd length
    2. Maintain center and right boundary of rightmost palindrome
    3. For each position, use mirror position for initial radius
       (mirror = 2*center - i)
    4. Expand outward, update center/right if we expanded past right
    5. This avoids redundant comparisons (linear time)

    COMPLEXITY:
    ──────────
    Time: O(n) — Each character examined at most twice
    Space: O(n) — Transformed string + radius array
    """
    if not s:
        return (0, -1)

    # Transform: "abc" → "|a|b|c|"
    transformed = '|' + '|'.join(s) + '|'
    n = len(transformed)
    radii = [0] * n

    center = 0
    right = 0

    for i in range(n):
        # Use mirror if within current palindrome
        if i < right:
            mirror = 2 * center - i
            radii[i] = min(right - i, radii[mirror])

        # Expand
        while (i - radii[i] - 1 >= 0 and
               i + radii[i] + 1 < n and
               transformed[i - radii[i] - 1] == transformed[i + radii[i] + 1]):
            radii[i] += 1

        # Update center and right
        if i + radii[i] > right:
            center = i
            right = i + radii[i]

    # Find max radius and its center
    max_radius = max(radii)
    center_idx = radii.index(max_radius)

    # Convert back to original string indices
    start = (center_idx - max_radius) // 2
    end = start + max_radius - 1

    return (start, end)


def manacher_count_palindromes(s: str) -> int:
    """
    Count all palindromic substrings using Manacher's algorithm.
    Time: O(n), Space: O(n)
    """
    transformed = '|' + '|'.join(s) + '|'
    n = len(transformed)
    radii = [0] * n

    center = right = 0
    total = 0

    for i in range(n):
        if i < right:
            mirror = 2 * center - i
            radii[i] = min(right - i, radii[mirror])

        while (i - radii[i] - 1 >= 0 and
               i + radii[i] + 1 < n and
               transformed[i - radii[i] - 1] == transformed[i + radii[i] + 1]):
            radii[i] += 1

        if i + radii[i] > right:
            center = i
            right = i + radii[i]

        # Each radius contributes ceil(radii[i] / 2) palindromes
        # For each unit of radius, we have a palindrome of that length
        total += (radii[i] + 1) // 2

    return total


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Run-Length Encoding (RLE) and Decoding
# ════════════════════════════════════════════════════════════════════════

def run_length_encode(s: str) -> str:
    """
    QUESTION:
    ─────────
    Perform Run-Length Encoding on a string. Replace consecutive repeated
    characters with the character followed by the count.

    Example:
        Input: "AAABBBCCDAABBB"
        Output: "A3B3C2D1A2B3"

    THOUGHT PROCESS:
    ────────────────
    1. Iterate through the string, counting consecutive identical chars
    2. When character changes, append char + count to result
    3. This is a simple but effective compression technique

    COMPLEXITY:
    ──────────
    Time: O(n) — Single pass
    Space: O(n) — Result string
    """
    if not s:
        return ""

    result = []
    count = 1

    for i in range(1, len(s)):
        if s[i] == s[i - 1]:
            count += 1
        else:
            result.append(f"{s[i - 1]}{count}")
            count = 1

    # Last character
    result.append(f"{s[-1]}{count}")
    return ''.join(result)


def run_length_decode(s: str) -> str:
    """
    Decode a Run-Length Encoded string.

    Example:
        Input: "A3B3C2D1A2B3"
        Output: "AAABBBCCDAABBB"
    """
    result = []
    i = 0
    while i < len(s):
        char = s[i]
        i += 1
        count_str = ""
        while i < len(s) and s[i].isdigit():
            count_str += s[i]
            i += 1
        result.append(char * int(count_str))
    return ''.join(result)


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Longest Common Substring (Suffix Array Approach)
# ════════════════════════════════════════════════════════════════════════

def longest_common_substring(s1: str, s2: str) -> str:
    """
    QUESTION:
    ─────────
    Find the longest common substring between two strings.

    Example:
        Input: s1 = "ABAB", s2 = "BABA"
        Output: "ABA" or "BAB"

    THOUGHT PROCESS:
    ────────────────
    1. DP approach: dp[i][j] = LCS ending at s1[i-1], s2[j-1]
       - If s1[i-1] == s2[j-1]: dp[i][j] = 1 + dp[i-1][j-1]
       - Else: dp[i][j] = 0
       - O(m × n) time, O(n) space optimized
    2. Suffix Array approach: Concatenate with sentinel, build suffix
       array + LCP array, find max LCP across different strings
    3. DP is simpler for interviews, O(mn) is acceptable for small strings

    COMPLEXITY:
    ──────────
    Time: O(m × n) — DP table
    Space: O(min(m, n)) — Space optimized
    """
    m, n = len(s1), len(s2)

    # Ensure s1 is the shorter string for space optimization
    if m > n:
        s1, s2 = s2, s1
        m, n = n, m

    prev = [0] * (n + 1)
    max_len = 0
    end_idx = 0

    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if s1[i - 1] == s2[j - 1]:
                curr[j] = 1 + prev[j - 1]
                if curr[j] > max_len:
                    max_len = curr[j]
                    end_idx = i  # end index in s1
        prev = curr

    return s1[end_idx - max_len:end_idx]


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Suffix Array Construction (Manber-Myers O(n log n))
# ════════════════════════════════════════════════════════════════════════

def build_suffix_array(s: str) -> List[int]:
    """
    QUESTION:
    ─────────
    Build a suffix array for string s in O(n log n) time.
    Suffix array: sorted order of all suffixes of s.

    Example:
        Input: "banana"
        Output: [5, 3, 1, 0, 4, 2]
        Suffixes: a, ana, anana, banana, na, nana

    THOUGHT PROCESS:
    ────────────────
    1. Start with sorting by first character (rank by ASCII)
    2. For k = 1, 2, 4, 8, ... until 2^k ≥ n:
       - Sort by rank and (rank of next 2^k chars)
       - Assign new ranks based on sorted order
    3. This is essentially a radix sort by pairs (rank[i], rank[i+k])

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Log n iterations, each O(n log n)
    Space: O(n) — Rank arrays
    """
    n = len(s)
    if n == 0:
        return []

    # Initial suffix array (indices) sorted by first character
    k = 1
    suffix_arr = list(range(n))

    # Initial rank: use character value
    rank = [ord(c) for c in s]
    tmp = [0] * n

    while True:
        # Sort by (rank[i], rank[i+k])
        suffix_arr.sort(key=lambda x: (rank[x], rank[x + k] if x + k < n else -1))

        # Assign new ranks
        tmp[suffix_arr[0]] = 0
        for i in range(1, n):
            prev = suffix_arr[i - 1]
            curr = suffix_arr[i]
            prev_key = (rank[prev], rank[prev + k] if prev + k < n else -1)
            curr_key = (rank[curr], rank[curr + k] if curr + k < n else -1)
            tmp[curr] = tmp[prev] + (1 if prev_key != curr_key else 0)

        rank, tmp = tmp, rank

        # If all ranks are distinct, we're done
        if rank[suffix_arr[-1]] == n - 1:
            break
        k *= 2

    return suffix_arr


def build_lcp_array(s: str, suffix_arr: List[int]) -> List[int]:
    """
    Build LCP (Longest Common Prefix) array using Kasai's algorithm.
    LCP[i] = longest common prefix between suffix_arr[i] and suffix_arr[i-1].

    Time: O(n), Space: O(n)
    """
    n = len(s)
    rank = [0] * n
    for i, sa in enumerate(suffix_arr):
        rank[sa] = i

    lcp = [0] * n
    h = 0

    for i in range(n):
        if rank[i] > 0:
            j = suffix_arr[rank[i] - 1]
            while i + h < n and j + h < n and s[i + h] == s[j + h]:
                h += 1
            lcp[rank[i]] = h
            if h > 0:
                h -= 1

    return lcp


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Unique Substrings Count (Using Suffix Array + LCP)
# ════════════════════════════════════════════════════════════════════════

def count_unique_substrings(s: str) -> int:
    """
    QUESTION:
    ─────────
    Count the number of distinct substrings of a string.

    Example:
        Input: "ababa"
        Output: 10  (a, b, ab, ba, aba, bab, abab, baba, ababa, ...)

    THOUGHT PROCESS:
    ────────────────
    1. Each suffix contributes len(suffix) substrings (all prefixes)
    2. But suffixes share common prefixes (LCP)
    3. Total unique = sum(len(suffix)) - sum(LCP)
       = n*(n+1)/2 - sum(LCP)
    4. This is a classic application of suffix array + LCP

    COMPLEXITY:
    ──────────
    Time: O(n log n) — Building suffix array
    Space: O(n) — Suffix array and LCP array
    """
    n = len(s)
    if n == 0:
        return 0

    sa = build_suffix_array(s)
    lcp = build_lcp_array(s, sa)

    total_substrings = n * (n + 1) // 2
    lcp_sum = sum(lcp)

    return total_substrings - lcp_sum


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("ADVANCED STRING ALGORITHMS — Interview Questions Demo")
    print("=" * 70)

    # Q1: KMP
    print("\n1️⃣  KMP Pattern Matching")
    print("-" * 40)
    text = "ABABDABACDABABCABAB"
    pattern = "ABABCABAB"
    result = kmp_search(text, pattern)
    print(f"   Text: \"{text}\"")
    print(f"   Pattern: \"{pattern}\"")
    print(f"   Matches at indices: {result}")

    # Q2: Rabin-Karp
    print("\n2️⃣  Rabin-Karp")
    print("-" * 40)
    text = "CCACCACCED"
    pattern = "ACC"
    result = rabin_karp(text, pattern)
    print(f"   Text: \"{text}\"")
    print(f"   Pattern: \"{pattern}\"")
    print(f"   Matches: {result}")

    # Q3: Z-Algorithm
    print("\n3️⃣  Z-Algorithm Search")
    print("-" * 40)
    result = z_search(text, pattern)
    print(f"   Text: \"{text}\"")
    print(f"   Pattern: \"{pattern}\"")
    print(f"   Z-Search matches: {result}")

    # Q4: Manacher's
    print("\n4️⃣  Manacher's Algorithm")
    print("-" * 40)
    for s in ["babad", "cbbd", "a", "ab"]:
        start, end = manacher(s)
        print(f"   \"{s}\" → longest palindrome: \"{s[start:end+1]}\"")
    print(f"   Palindromic substrings in \"ababa\": {manacher_count_palindromes('ababa')}")

    # Q5: Run-Length Encoding
    print("\n5️⃣  Run-Length Encoding")
    print("-" * 40)
    original = "AAABBBCCDAABBB"
    encoded = run_length_encode(original)
    decoded = run_length_decode(encoded)
    print(f"   Original: \"{original}\"")
    print(f"   Encoded:  \"{encoded}\"")
    print(f"   Decoded:  \"{decoded}\"")

    # Q6: Longest Common Substring
    print("\n6️⃣  Longest Common Substring")
    print("-" * 40)
    s1, s2 = "ABAB", "BABA"
    result = longest_common_substring(s1, s2)
    print(f"   s1=\"{s1}\", s2=\"{s2}\"")
    print(f"   LCS: \"{result}\"")

    # Q7: Suffix Array
    print("\n7️⃣  Suffix Array Construction")
    print("-" * 40)
    s = "banana"
    sa = build_suffix_array(s)
    lcp = build_lcp_array(s, sa)
    print(f"   String: \"{s}\"")
    print(f"   Suffix Array: {sa}")
    print(f"   LCP Array: {lcp}")
    for idx in sa:
        print(f"     {idx:2d}: \"{s[idx:]}\"")

    # Q8: Unique Substrings
    print("\n8️⃣  Count Unique Substrings")
    print("-" * 40)
    for s in ["ababa", "aaaa", "abc"]:
        print(f"   \"{s}\": {count_unique_substrings(s)} unique substrings")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
