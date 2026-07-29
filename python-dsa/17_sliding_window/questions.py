"""
SLIDING WINDOW — Core Concepts & Interview Questions
=====================================================

Core Concepts:
──────────────
• Efficient technique for processing arrays/strings using a window
  that slides over the data
• Two main types:
  1. Fixed window size: window slides by 1, maintaining constant size
  2. Variable window size: window expands/contracts based on constraints

When to Use Sliding Window:
───────────────────────────
• Problem involves subarray or substring
• Looking for: max/min/sum of subarrays, or longest/shortest substring
  satisfying a condition
• O(n) is required (or at least achievable)
• Brute force would be O(n²) or O(n³)

Template for Variable Window:
─────────────────────────────
left = 0
for right in range(len(array)):
    # Add arr[right] to window
    while not_meeting_condition():
        # Remove arr[left] from window
        left += 1
    # Update result (window is valid at this point)

Template for Fixed Window:
──────────────────────────
for right in range(len(array)):
    # Add arr[right] to window
    if right >= k - 1:  # Window is fully formed
        # Record result using window
        # Remove arr[left] from window
        left += 1
"""

from typing import List, Dict, Optional
from collections import defaultdict, Counter


# ════════════════════════════════════════════════════════════════════════
# QUESTION 1: Longest Substring with At Most K Distinct Characters
# ════════════════════════════════════════════════════════════════════════

def length_of_longest_substring_k_distinct(s: str, k: int) -> int:
    """
    QUESTION:
    ─────────
    Given a string s and an integer k, find the length of the longest
    substring that contains at most k distinct characters.

    Example:
        Input: s = "eceba", k = 2
        Output: 3  ("ece")

    THOUGHT PROCESS:
    ────────────────
    1. Maintain a window [left, right] with at most k distinct chars
    2. Use a hash map to count character frequencies in the window
    3. When window has > k distinct chars, shrink from left
    4. Track maximum window length

    COMPLEXITY:
    ──────────
    Time: O(n) — Each character visited at most twice
    Space: O(k) — Hash map of at most k characters
    """
    if k == 0:
        return 0

    freq = defaultdict(int)
    max_len = 0
    left = 0

    for right, char in enumerate(s):
        freq[char] += 1

        # Shrink window while we have too many distinct chars
        while len(freq) > k:
            left_char = s[left]
            freq[left_char] -= 1
            if freq[left_char] == 0:
                del freq[left_char]
            left += 1

        max_len = max(max_len, right - left + 1)

    return max_len


# ════════════════════════════════════════════════════════════════════════
# QUESTION 2: Longest Repeating Character Replacement
# ════════════════════════════════════════════════════════════════════════

def character_replacement(s: str, k: int) -> int:
    """
    QUESTION:
    ─────────
    Given a string s and an integer k, find the length of the longest
    substring containing the same character after at most k replacements.

    Example:
        Input: s = "ABAB", k = 2
        Output: 4  ("ABAB" → "AAAA" or "BBBB")
        Input: s = "AABABBA", k = 1
        Output: 4  ("AABA" or "ABBB")

    THOUGHT PROCESS:
    ────────────────
    1. For a substring to be valid: length - max_freq ≤ k
       (we can change all other characters to the most frequent one)
    2. Maintain window with frequency counts
    3. Expand right, if invalid, shrink left
    4. Track max_freq in current window (optimized: overall max seen)

    COMPLEXITY:
    ──────────
    Time: O(n) — Each character visited at most twice
    Space: O(1) — At most 26 characters (uppercase letters)
    """
    freq = [0] * 26
    max_len = 0
    max_freq = 0  # Best optimization: track overall max frequency
    left = 0

    for right, char in enumerate(s):
        idx = ord(char) - ord('A')
        freq[idx] += 1
        max_freq = max(max_freq, freq[idx])

        # Window is valid if: window_size - max_freq ≤ k
        while (right - left + 1) - max_freq > k:
            left_idx = ord(s[left]) - ord('A')
            freq[left_idx] -= 1
            left += 1
            # Note: we don't decrease max_freq here — it's a non-strict bound
            # This optimization works because we only care about the max

        max_len = max(max_len, right - left + 1)

    return max_len


# ════════════════════════════════════════════════════════════════════════
# QUESTION 3: Minimum Size Subarray Sum
# ════════════════════════════════════════════════════════════════════════

def min_subarray_len(target: int, nums: List[int]) -> int:
    """
    QUESTION:
    ─────────
    Given an array of positive integers and a target, find the minimum
    length of a contiguous subarray whose sum ≥ target. If none, return 0.

    Example:
        Input: target = 7, nums = [2, 3, 1, 2, 4, 3]
        Output: 2  ([4, 3])

    THOUGHT PROCESS:
    ────────────────
    1. Variable-size sliding window
    2. Expand right until sum ≥ target
    3. Shrink left while sum ≥ target, tracking minimum length
    4. This finds the smallest window satisfying the condition

    COMPLEXITY:
    ──────────
    Time: O(n) — Each element added and removed at most once
    Space: O(1) — Only variables
    """
    left = 0
    current_sum = 0
    min_len = float('inf')

    for right, num in enumerate(nums):
        current_sum += num

        # Shrink from left while condition holds
        while current_sum >= target:
            min_len = min(min_len, right - left + 1)
            current_sum -= nums[left]
            left += 1

    return 0 if min_len == float('inf') else min_len


# ════════════════════════════════════════════════════════════════════════
# QUESTION 4: Fruit Into Baskets (Max len with at most 2 types)
# ════════════════════════════════════════════════════════════════════════

def total_fruit(fruits: List[int]) -> int:
    """
    QUESTION:
    ─────────
    You have two baskets, each can hold only one type of fruit.
    Pick fruits in a row. Maximize the number of fruits collected.

    Equivalent to: Longest subarray with at most 2 distinct values.

    Example:
        Input: fruits = [1, 2, 1]
        Output: 3
        Input: fruits = [0, 1, 2, 2]
        Output: 3  ([1, 2, 2])

    THOUGHT PROCESS:
    ────────────────
    1. Same as "at most 2 distinct characters" problem
    2. Sliding window with hash map tracking frequencies
    3. Shrink when we have more than 2 types

    COMPLEXITY:
    ──────────
    Time: O(n) — Linear scan
    Space: O(1) — At most 3 types stored
    """
    freq = {}
    max_count = 0
    left = 0

    for right, fruit in enumerate(fruits):
        freq[fruit] = freq.get(fruit, 0) + 1

        while len(freq) > 2:
            left_fruit = fruits[left]
            freq[left_fruit] -= 1
            if freq[left_fruit] == 0:
                del freq[left_fruit]
            left += 1

        max_count = max(max_count, right - left + 1)

    return max_count


# ════════════════════════════════════════════════════════════════════════
# QUESTION 5: Permutation in String
# ════════════════════════════════════════════════════════════════════════

def check_inclusion(s1: str, s2: str) -> bool:
    """
    QUESTION:
    ─────────
    Given two strings s1 and s2, return true if s2 contains a permutation
    of s1 as a contiguous substring.

    Example:
        Input: s1 = "ab", s2 = "eidbaooo"
        Output: true  (s2 has "ba")
        Input: s1 = "ab", s2 = "eidboaoo"
        Output: false

    THOUGHT PROCESS:
    ────────────────
    1. Fixed window size = len(s1)
    2. Count frequencies in s1, compare with each window in s2
    3. Use a "matches" counter to avoid O(26) comparison each time
    4. Only need to compare counts at string boundaries

    COMPLEXITY:
    ──────────
    Time: O(n) — n = len(s2)
    Space: O(1) — Two 26-element arrays
    """
    if len(s1) > len(s2):
        return False

    s1_count = [0] * 26
    window_count = [0] * 26

    for char in s1:
        s1_count[ord(char) - ord('a')] += 1

    for i, char in enumerate(s2):
        # Add new char to window
        window_count[ord(char) - ord('a')] += 1

        # Remove char that falls out of window
        if i >= len(s1):
            window_count[ord(s2[i - len(s1)]) - ord('a')] -= 1

        # Check if window matches s1 frequencies
        if i >= len(s1) - 1:
            if window_count == s1_count:
                return True

    return False


# ════════════════════════════════════════════════════════════════════════
# QUESTION 6: Max Consecutive Ones III (Flip at most k zeros)
# ════════════════════════════════════════════════════════════════════════

def longest_ones(nums: List[int], k: int) -> int:
    """
    QUESTION:
    ─────────
    Given a binary array nums and an integer k, return the maximum number
    of consecutive 1's in the array if you can flip at most k zeros to 1.

    Example:
        Input: nums = [1,1,1,0,0,0,1,1,1,1,0], k = 2
        Output: 6  (flip two zeros → [1,1,1,0,0,1,1,1,1,1,1])

    THOUGHT PROCESS:
    ────────────────
    1. Window is valid if number of zeros ≤ k
    2. Expand right, if we see a zero, decrement k
    3. If zeros > k, shrink left until valid again
    4. Track max window length

    COMPLEXITY:
    ──────────
    Time: O(n) — Linear scan
    Space: O(1) — Only variables
    """
    left = 0
    zero_count = 0
    max_len = 0

    for right, num in enumerate(nums):
        if num == 0:
            zero_count += 1

        while zero_count > k:
            if nums[left] == 0:
                zero_count -= 1
            left += 1

        max_len = max(max_len, right - left + 1)

    return max_len


# ════════════════════════════════════════════════════════════════════════
# QUESTION 7: Substring with Concatenation of All Words
# ════════════════════════════════════════════════════════════════════════

def find_substring(s: str, words: List[str]) -> List[int]:
    """
    QUESTION:
    ─────────
    Given a string s and an array of words (all same length), find all
    starting indices of substrings that are a concatenation of each word
    exactly once (in any order).

    Example:
        Input: s = "barfoothefoobarman", words = ["foo", "bar"]
        Output: [0, 9]  ("barfoo" at 0, "foobar" at 9)

    THOUGHT PROCESS:
    ────────────────
    1. Fixed window size = len(words) * word_len
    2. Use a sliding window with two counters:
       - Expected: frequency of each word in words
       - Seen: frequency in current window
    3. Slide by word_len (not 1) since we're matching whole words
    4. Need to consider all starting offsets [0, word_len-1]

    COMPLEXITY:
    ──────────
    Time: O(n × m) — n = len(s), m = word_len (small)
    Space: O(k) — k = unique words
    """
    if not s or not words:
        return []

    word_len = len(words[0])
    total_len = len(words) * word_len
    word_count = Counter(words)

    result = []

    # Try each possible offset within a word
    for offset in range(word_len):
        left = offset
        seen = defaultdict(int)
        count = 0

        for right in range(offset, len(s) - word_len + 1, word_len):
            word = s[right:right + word_len]

            if word in word_count:
                seen[word] += 1
                count += 1

                # If we have too many of this word, shrink window
                while seen[word] > word_count[word]:
                    left_word = s[left:left + word_len]
                    seen[left_word] -= 1
                    count -= 1
                    left += word_len

                # If we've matched all words, record result
                if count == len(words):
                    result.append(left)
                    # Shrink to find more
                    left_word = s[left:left + word_len]
                    seen[left_word] -= 1
                    count -= 1
                    left += word_len
            else:
                # Word not in dictionary, reset window
                seen.clear()
                count = 0
                left = right + word_len

    return result


# ════════════════════════════════════════════════════════════════════════
# QUESTION 8: Minimum Window Subsequence
# ════════════════════════════════════════════════════════════════════════

def min_window_subsequence(s: str, t: str) -> str:
    """
    QUESTION:
    ─────────
    Given strings s and t, find the minimum contiguous substring of s
    that has t as a subsequence (not necessarily contiguous).

    Example:
        Input: s = "abcdebdde", t = "bde"
        Output: "bcde"  (or "bdde", both valid)

    THOUGHT PROCESS:
    ────────────────
    1. Not a standard sliding window — we need "subsequence" not substring
    2. Two-pass approach:
       a) Find match window scanning forward (match t)
       b) Optimize from the right (find shortest match)
    3. For each start position, match as much of t as possible, then
       backtrack from the end to minimize the window

    COMPLEXITY:
    ──────────
    Time: O(|s| × |t|) — Worst case
    Space: O(1) — Only variables
    """
    if not s or not t:
        return ""

    min_len = float('inf')
    result = ""
    i = 0  # index in s

    while i < len(s):
        # Forward pass: match t in s
        j = 0  # index in t
        while i < len(s) and j < len(t):
            if s[i] == t[j]:
                j += 1
            i += 1

        # If we matched all of t
        if j == len(t):
            # Backward pass: optimize window
            end = i  # Save end position
            i -= 1
            j = len(t) - 1
            while j >= 0:
                if s[i] == t[j]:
                    j -= 1
                i -= 1
            i += 1  # Start of optimal window

            # Update result
            window_len = end - i
            if window_len < min_len:
                min_len = window_len
                result = s[i:end]

        # Move to next possible start
        i += 1

    return result


# ════════════════════════════════════════════════════════════════════════
# DEMO
# ════════════════════════════════════════════════════════════════════════

def demo():
    print("=" * 70)
    print("SLIDING WINDOW — Interview Questions Demo")
    print("=" * 70)

    # Q1
    print("\n1️⃣  Longest Substring with At Most K Distinct")
    print("-" * 40)
    s, k = "eceba", 2
    print(f"   s=\"{s}\", k={k}")
    print(f"   Length: {length_of_longest_substring_k_distinct(s, k)}")

    # Q2
    print("\n2️⃣  Longest Repeating Character Replacement")
    print("-" * 40)
    print(f"   s=\"ABAB\", k=2: {character_replacement('ABAB', 2)}")
    print(f"   s=\"AABABBA\", k=1: {character_replacement('AABABBA', 1)}")

    # Q3
    print("\n3️⃣  Minimum Size Subarray Sum")
    print("-" * 40)
    nums = [2, 3, 1, 2, 4, 3]
    target = 7
    print(f"   nums={nums}, target={target}")
    print(f"   Min length: {min_subarray_len(target, nums)}")

    # Q4
    print("\n4️⃣  Fruit Into Baskets")
    print("-" * 40)
    fruits = [1, 2, 1]
    print(f"   fruits={fruits}: {total_fruit(fruits)}")
    fruits2 = [0, 1, 2, 2]
    print(f"   fruits={fruits2}: {total_fruit(fruits2)}")

    # Q5
    print("\n5️⃣  Permutation in String")
    print("-" * 40)
    print(f"   s1=\"ab\", s2=\"eidbaooo\": {check_inclusion('ab', 'eidbaooo')}")
    print(f"   s1=\"ab\", s2=\"eidboaoo\": {check_inclusion('ab', 'eidboaoo')}")

    # Q6
    print("\n6️⃣  Max Consecutive Ones III")
    print("-" * 40)
    nums = [1, 1, 1, 0, 0, 0, 1, 1, 1, 1, 0]
    k = 2
    print(f"   nums={nums}, k={k}")
    print(f"   Max len: {longest_ones(nums, k)}")

    # Q7
    print("\n7️⃣  Substring with Concatenation of All Words")
    print("-" * 40)
    s = "barfoothefoobarman"
    words = ["foo", "bar"]
    print(f"   s=\"{s}\", words={words}")
    print(f"   Indices: {find_substring(s, words)}")

    # Q8
    print("\n8️⃣  Minimum Window Subsequence")
    print("-" * 40)
    print(f"   s=\"abcdebdde\", t=\"bde\": \"{min_window_subsequence('abcdebdde', 'bde')}\"")

    # Q1 revisited: edge case
    print("\n   🔍 Edge Case: k=0 with distinct chars")
    print(f"   s=\"abc\", k=0: {length_of_longest_substring_k_distinct('abc', 0)}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    demo()
